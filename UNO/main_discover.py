import torch
import torch.nn as nn
import torch.nn.functional as F
import pytorch_lightning as pl
from pl_bolts.optimizers.lr_scheduler import LinearWarmupCosineAnnealingLR
from pytorch_lightning.metrics import Accuracy

from utils.data import get_datamodule
from utils.nets import MultiHeadResNet
from utils.eval import ClusterMetrics
from utils.sinkhorn_knopp import SinkhornKnopp

import numpy as np
from argparse import ArgumentParser
from datetime import datetime


# Initialize the basic argument parser and take input arguments
parser = ArgumentParser()
parser.add_argument("--dataset", default="CIFAR100", type=str, help="dataset")
parser.add_argument("--imagenet_split", default="A", type=str, help="imagenet split [A,B,C]")
parser.add_argument("--download", default=False, action="store_true", help="wether to download")
parser.add_argument("--data_dir", default="datasets", type=str, help="data directory")
parser.add_argument("--log_dir", default="logs", type=str, help="log directory")
parser.add_argument("--batch_size", default=256, type=int, help="batch size")
parser.add_argument("--num_workers", default=10, type=int, help="number of workers")
parser.add_argument("--arch", default="resnet18", type=str, help="backbone architecture")
parser.add_argument("--base_lr", default=0.4, type=float, help="learning rate")
parser.add_argument("--min_lr", default=0.001, type=float, help="min learning rate")
parser.add_argument("--momentum_opt", default=0.9, type=float, help="momentum for optimizer")
parser.add_argument("--weight_decay_opt", default=1.5e-4, type=float, help="weight decay")
parser.add_argument("--warmup_epochs", default=10, type=int, help="warmup epochs")
parser.add_argument("--proj_dim", default=256, type=int, help="projected dim")
parser.add_argument("--hidden_dim", default=2048, type=int, help="hidden dim in proj/pred head")
parser.add_argument("--overcluster_factor", default=3, type=int, help="overclustering factor")
parser.add_argument("--num_heads", default=5, type=int, help="number of heads for clustering")
parser.add_argument("--num_hidden_layers", default=1, type=int, help="number of hidden layers")
parser.add_argument("--num_iters_sk", default=3, type=int, help="number of iters for Sinkhorn")
parser.add_argument("--epsilon_sk", default=0.05, type=float, help="epsilon for the Sinkhorn")
parser.add_argument("--temperature", default=0.1, type=float, help="softmax temperature")
parser.add_argument("--comment", default=datetime.now().strftime("%b%d_%H-%M-%S"), type=str)
parser.add_argument("--project", default="UNO", type=str, help="wandb project")
parser.add_argument("--entity", default=None, type=str, help="wandb entity")
parser.add_argument("--offline", default=False, action="store_true", help="disable wandb")
parser.add_argument("--num_labeled_classes", default=80, type=int, help="number of labeled classes")
parser.add_argument("--num_unlabeled_classes", default=20, type=int, help="number of unlab classes")
parser.add_argument("--pretrained", type=str, help="pretrained checkpoint path")
parser.add_argument("--multicrop", default=False, action="store_true", help="activates multicrop")
parser.add_argument("--num_large_crops", default=2, type=int, help="number of large crops")
parser.add_argument("--num_small_crops", default=2, type=int, help="number of small crops")


class Discoverer(pl.LightningModule):
    """Built the correct model depending on the input arguments"""
    def __init__(self, **kwargs):
        """Initialize the model"""
        # Call the initializer of the parent class
        super().__init__()
        # Store all the provided arguments under the self.hparams attribute of the current class
        self.save_hyperparameters({k: v for (k, v) in kwargs.items() if not callable(v)})

        # Build a MultiHeadResNet with a 'h' head for labeled classes and a 'g' multi-head for unlabeled samples
        self.model = MultiHeadResNet(
            arch=self.hparams.arch,
            # True if the string CIFAR is present in self.hparams.dataset (Normally true since dataset=CIFAR100)
            low_res="CIFAR" in self.hparams.dataset,
            num_labeled=self.hparams.num_labeled_classes,
            num_unlabeled=self.hparams.num_unlabeled_classes,
            # Parameters for the unlabeled multi-head
            proj_dim=self.hparams.proj_dim,
            hidden_dim=self.hparams.hidden_dim,
            overcluster_factor=self.hparams.overcluster_factor,
            num_heads=self.hparams.num_heads,
            num_hidden_layers=self.hparams.num_hidden_layers,
        )

        # Load the model parameter from the specified path and map it to the current device
        state_dict = torch.load(self.hparams.pretrained, map_location=self.device)
        # Convert the loaded data into a dictionary if the unlabeled key is missing
        state_dict = {k: v for k, v in state_dict.items() if ("unlab" not in k)}
        # Apply the parameters to the current model without strictly forcing it (now the model has also the MultiHead)
        self.model.load_state_dict(state_dict, strict=False)

        # Add Sinkhorn-Knopp algorithm, this is used to penalize the situation in which the computed logits are equal
        # for any input sample. This could happen since we do not have any constraint that enforces consistency
        # between the two views (augmentations) of a single input image. So, we need to avoid this problem to learn.
        self.sk = SinkhornKnopp(num_iters=self.hparams.num_iters_sk, epsilon=self.hparams.epsilon_sk)

        # Define two list of modules to keep track of the clustering metrics(acc+nmi+ari) and of the accuracy
        self.metrics = torch.nn.ModuleList(
            [
                ClusterMetrics(self.hparams.num_heads),
                ClusterMetrics(self.hparams.num_heads),
                Accuracy(),
            ]
        )
        self.metrics_inc = torch.nn.ModuleList(
            [
                ClusterMetrics(self.hparams.num_heads),
                ClusterMetrics(self.hparams.num_heads),
                Accuracy(),
            ]
        )

        # Buffer (save but do not consider it as a NN parameter) a tensor of zeros used to track the loss over the heads
        self.register_buffer("loss_per_head", torch.zeros(self.hparams.num_heads))

    def configure_optimizers(self):
        """Configure SGD optimizer and LR scheduler"""
        optimizer = torch.optim.SGD(
            self.model.parameters(),
            lr=self.hparams.base_lr,
            momentum=self.hparams.momentum_opt,
            weight_decay=self.hparams.weight_decay_opt,
        )
        scheduler = LinearWarmupCosineAnnealingLR(
            optimizer,
            warmup_epochs=self.hparams.warmup_epochs,
            max_epochs=self.hparams.max_epochs,
            warmup_start_lr=self.hparams.min_lr,
            eta_min=self.hparams.min_lr,
        )
        return [optimizer], [scheduler]

    def cross_entropy_loss(self, preds, targets):
        """CE loss with Temperature parameter"""
        preds = F.log_softmax(preds / self.hparams.temperature, dim=-1)
        return torch.mean(-torch.sum(targets * preds, dim=-1), dim=-1)

    def swapped_prediction(self, logits, targets):
        loss = 0
        # For each view
        for view in range(self.hparams.num_large_crops):
            # For the opposite view
            for other_view in np.delete(range(self.hparams.num_crops), view):
                # Increment the loss by the CE resulting from the logits of one view and the targets of the other
                loss += self.cross_entropy_loss(logits[other_view], targets[view])
        return loss / (self.hparams.num_large_crops * (self.hparams.num_crops - 1))

    def forward(self, x):
        return self.model(x)

    def on_epoch_start(self):
        # Build a tensor filled with the scalar value 0, with the same size as input tensor
        self.loss_per_head = torch.zeros_like(self.loss_per_head)

    def unpack_batch(self, batch):
        # When working with imagenet get the data in the following way
        if self.hparams.dataset == "ImageNet":
            views_lab, labels_lab, views_unlab, labels_unlab = batch
            views = [torch.cat([vl, vu]) for vl, vu in zip(views_lab, views_unlab)]
            labels = torch.cat([labels_lab, labels_unlab])
        # Otherwise, when working on CIFAR use this procedure
        else:
            views, labels = batch

        # Generate a boolean mask label full of True for the samples which have a label lower than the number of labeled
        # classes. It means that the labeled samples are represented with True, the unlabeled with False.
        mask_lab = labels < self.hparams.num_labeled_classes
        return views, labels, mask_lab

    def training_step(self, batch, _):
        # Get views, labels and mask labels from the current batch
        views, labels, mask_lab = self.unpack_batch(batch)
        nlc = self.hparams.num_labeled_classes

        # Normalize the prototype classifier
        self.model.normalize_prototypes()

        # Compute the output for this batch of views
        outputs = self.model(views)

        # Change the dimension of the labeled logit output tensor
        outputs["logits_lab"] = (outputs["logits_lab"].unsqueeze(1).expand(-1, self.hparams.num_heads, -1, -1))
        # Concatenate the logits of the labeled and unlabeled head
        logits = torch.cat([outputs["logits_lab"], outputs["logits_unlab"]], dim=-1)
        # Concatenate the logits of the labeled and unlabeled_over head
        logits_over = torch.cat([outputs["logits_lab"], outputs["logits_unlab_over"]], dim=-1)

        # Create a target tensor for the labeled samples full of zeros and use one-hot encoding (with float variables)
        targets_lab = (
            F.one_hot(labels[mask_lab], num_classes=self.hparams.num_labeled_classes)
            .float()
            .to(self.device)
        )
        # Create two tensors full of zeros with the same size as logits and logits_over
        targets = torch.zeros_like(logits)
        targets_over = torch.zeros_like(logits_over)

        # For each crop and for each head
        for v in range(self.hparams.num_large_crops):
            for h in range(self.hparams.num_heads):
                # Assign to the targets and targets_over tensors the value of the labeled target
                targets[v, h, mask_lab, :nlc] = targets_lab.type_as(targets)
                targets_over[v, h, mask_lab, :nlc] = targets_lab.type_as(targets)

                # Generate pseudo-labels with sinkhorn-knopp to fill the unlab targets dimension
                targets[v, h, ~mask_lab, nlc:] = self.sk(outputs["logits_unlab"][v, h, ~mask_lab]).type_as(targets)
                targets_over[v, h, ~mask_lab, nlc:] = self.sk(outputs["logits_unlab_over"][v, h, ~mask_lab]).type_as(targets)

        # Compute swapped prediction loss
        loss_cluster = self.swapped_prediction(logits, targets)
        loss_overcluster = self.swapped_prediction(logits_over, targets_over)

        # Update tracker for the best head
        self.loss_per_head += loss_cluster.clone().detach()

        # Compute the total loss
        loss_cluster = loss_cluster.mean()
        loss_overcluster = loss_overcluster.mean()
        loss = (loss_cluster + loss_overcluster) / 2

        # Save the losses and the learning-rate, then log them
        results = {
            "loss": loss.detach(),
            "loss_cluster": loss_cluster.mean(),
            "loss_overcluster": loss_overcluster.mean(),
            "lr": self.trainer.optimizers[0].param_groups[0]["lr"],
        }
        self.log_dict(results, on_step=False, on_epoch=True, sync_dist=True)

        # Return the loss
        return loss

    def validation_step(self, batch, batch_idx, dl_idx):
        # Get images and labels from the current batch
        images, labels = batch
        # Get a tag from the dataloader_mapping of the current datamodule
        tag = self.trainer.datamodule.dataloader_mapping[dl_idx]

        # Compute the output
        outputs = self(images)

        # If the tag is unlab then use the clustering head
        if "unlab" in tag:
            # Extract the logits for the unlabeled sample
            preds = outputs["logits_unlab"]
            # Concatenate it to the labeled logits un-squeezing and expanding the tensor
            preds_inc = torch.cat(
                [
                    outputs["logits_lab"].unsqueeze(0).expand(self.hparams.num_heads, -1, -1),
                    outputs["logits_unlab"],
                ],
                dim=-1,
            )
        # Otherwise, if there is no "unlab" in tag then use supervised classifier
        else:
            # Extract the logits for the labeled sample
            preds = outputs["logits_lab"]
            # Concatenate it to the unlabeled logits
            best_head = torch.argmin(self.loss_per_head)
            preds_inc = torch.cat(
                [outputs["logits_lab"], outputs["logits_unlab"][best_head]], dim=-1
            )

        # Extract only the class with the highest logits as prediction for both the tensor
        preds = preds.max(dim=-1)[1]
        preds_inc = preds_inc.max(dim=-1)[1]

        # Add the two predictions to the metrics
        self.metrics[dl_idx].update(preds, labels)
        self.metrics_inc[dl_idx].update(preds_inc, labels)

    def validation_epoch_end(self, _):
        # Compute the metric results
        results = [m.compute() for m in self.metrics]
        results_inc = [m.compute() for m in self.metrics_inc]

        # log metrics
        for dl_idx, (result, result_inc) in enumerate(zip(results, results_inc)):
            # Get a prefix from the dataloader_mapping of the current datamodule
            prefix = self.trainer.datamodule.dataloader_mapping[dl_idx]
            prefix_inc = "incremental/" + prefix
            # If the prefix encompasses "unlab" evaluate and log metrics over different unlabeled heads
            if "unlab" in prefix:
                for (metric, values), (_, values_inc) in zip(result.items(), result_inc.items()):
                    name = "/".join([prefix, metric])
                    name_inc = "/".join([prefix_inc, metric])
                    avg = torch.stack(values).mean()
                    avg_inc = torch.stack(values_inc).mean()
                    best = values[torch.argmin(self.loss_per_head)]
                    best_inc = values_inc[torch.argmin(self.loss_per_head)]
                    self.log(name + "/avg", avg, sync_dist=True)
                    self.log(name + "/best", best, sync_dist=True)
                    self.log(name_inc + "/avg", avg_inc, sync_dist=True)
                    self.log(name_inc + "/best", best_inc, sync_dist=True)
            # Otherwise just log metrics for the labeled head
            else:
                self.log(prefix + "/acc", result)
                self.log(prefix_inc + "/acc", result_inc)


def main(args):
    # Instantiate a datamodule in 'discover' mode over the dataset specified by args (default = CIFAR100)
    dm = get_datamodule(args, "discover")

    # Define the name of the current run
    run_name = "-".join(["discover", args.arch, args.dataset, args.comment])
    # Define an instance of Pytorch-Lightning WandB logger using the arguments of the parser and the name of the run
    wandb_logger = pl.loggers.WandbLogger(
        save_dir=args.log_dir,
        name=run_name,
        project=args.project,
        entity=args.entity,
        offline=args.offline,
    )

    # Instantiate a model giving in input all the available arguments as a dictionary to the Discoverer class
    model = Discoverer(**args.__dict__)

    # Define a Pytorch-Lightning Trainer using the parameter from the Pytorch-Lightning parser, using wandb logger
    trainer = pl.Trainer.from_argparse_args(args, logger=wandb_logger)
    # Fit the model over the data-module
    trainer.fit(model, dm)


if __name__ == "__main__":
    # Extend the basic ArgParser with a PyTorch-Lightning parser, this will introduce all the NN-training terms
    parser = pl.Trainer.add_argparse_args(parser)
    # Parse the arguments and make them ready for the retrieval
    args = parser.parse_args()

    # Set the num_classes argument as the sum of num_labeled_classes and num_unlabeled_classes
    args.num_classes = args.num_labeled_classes + args.num_unlabeled_classes

    # If multi-crop argument is false then set the number of num_small_crops to 0
    if not args.multicrop:
        args.num_small_crops = 0
    # Set the num_crops argument as the sum of large and small crops
    args.num_crops = args.num_large_crops + args.num_small_crops

    # Run the main giving all the arguments (basic + training)
    main(args)
