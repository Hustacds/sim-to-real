import shutil

import numpy as np
from torch import nn, optim, torch
from torch.autograd import Variable
from torch.utils.data import DataLoader
import torch.nn.functional as F

from simple_joints_lstm.pusher_lstm import LstmSimpleNet2Pusher
from simple_joints_lstm.mujoco_traintest_dataset_pusher_simple import MujocoTraintestPusherSimpleDataset
from utils.plot import VisdomExt
import os

try:
    from hyperdash import Experiment

    hyperdash_support = True
except:
    hyperdash_support = False

HIDDEN_NODES = 128
LSTM_LAYERS = 3
EXPERIMENT = 1
EPOCHS = 200
ACTION_STEPS = 5
# TRUNCATED_BACKPROP_N = 20
# EPISODE_LEN = 100

DATASET_PATH = "./data-collection/mujoco_pusher3dof_simple_{}act.npz".format(ACTION_STEPS)
MODEL_PATH = "./trained_models/lstm_pusher3dof_simple_{}ac_{}l_{}n.pt".format(
    ACTION_STEPS,
    LSTM_LAYERS,
    HIDDEN_NODES
)
MODEL_PATH_BEST = "./trained_models/lstm_pusher3dof_simple_{}ac_{}l_{}n_best.pt".format(
    ACTION_STEPS,
    LSTM_LAYERS,
    HIDDEN_NODES
)
TRAIN = True
CONTINUE = False
CUDA = True

print(MODEL_PATH_BEST)

batch_size = 1
dataset_train = MujocoTraintestPusherSimpleDataset(DATASET_PATH, for_training=True)
dataloader_train = DataLoader(dataset_train, batch_size=batch_size, shuffle=True)

dataset_test = MujocoTraintestPusherSimpleDataset(DATASET_PATH, for_training=False)
dataloader_test = DataLoader(dataset_test, batch_size=batch_size, shuffle=True)

net = LstmSimpleNet2Pusher(15, 6, use_cuda=CUDA, normalized=False)

print(net)

if CUDA:
    net.cuda()


# viz = VisdomExt([["loss", "validation loss"],["diff"]],[dict(title='LSTM loss', xlabel='iteration', ylabel='loss'),
# dict(title='Diff loss', xlabel='iteration', ylabel='error')])


def makeIntoVariables(episode):
    _input = np.concatenate([
        episode["state_next_sim"],
        episode["state_current_real"],
        episode["actions"]
    ], axis=2)
    _input = torch.from_numpy(_input)
    _output = episode["state_next_real"]

    if CUDA:
        _input = _input.cuda()
        _output = _output.cuda()

    x, y = Variable(
        _input,
        requires_grad=False
    ), Variable(
        _output,
        requires_grad=False
    )

    return x, y


def printEpochLoss(epoch_idx, loss_valid, loss_epoch, diff_epoch):
    print("epoch {}, "
          "train loss: {}, "
          "test loss: {}, "
          "diff: {}, ".format(
        epoch_idx,
        loss_epoch,
        loss_valid,
        diff_epoch
    ))


def saveModel(state, epoch, loss_epoch, diff_epoch, is_best, episode_idx):
    torch.save({
        "epoch": epoch,
        "episodes": episode_idx + 1,
        "state_dict": state,
        "epoch_avg_loss": np.mean(loss_epoch),
        "epoch_avg_diff": np.mean(diff_epoch)
    }, MODEL_PATH)
    if is_best:
        shutil.copyfile(MODEL_PATH, MODEL_PATH_BEST)


def loadModel(optional=True):
    model_exists = os.path.isfile(MODEL_PATH_BEST)
    if model_exists:
        checkpoint = torch.load(MODEL_PATH_BEST)
        net.load_state_dict(checkpoint['state_dict'])
        print("MODEL LOADED, CONTINUING TRAINING")
        return "TRAINING AVG LOSS: {}\n" \
               "TRAINING AVG DIFF: {}".format(
            checkpoint["epoch_avg_loss"], checkpoint["epoch_avg_diff"])
    else:
        if optional:
            pass  # model loading was optional, so nothing to do
        else:
            # shit, no model
            raise Exception("model couldn't be found:", MODEL_PATH_BEST)


loss_function = nn.MSELoss()
if hyperdash_support:
    exp = Experiment("simple lstm - pusher simple")
    exp.param("layers", LSTM_LAYERS)
    exp.param("nodes", HIDDEN_NODES)
    exp.param("action steps", ACTION_STEPS)

if TRAIN:
    optimizer = optim.Adam(net.parameters())
    if CONTINUE:
        old_model_string = loadModel(optional=True)
        print(old_model_string)
else:
    old_model_string = loadModel(optional=False)

loss_min = [float('inf')]

for epoch in np.arange(EPOCHS):

    loss_epoch = []
    diff_epoch = []

    for epi, data in enumerate(dataloader_train):
        x, y = makeIntoVariables(data)

        # reset hidden lstm units
        net.zero_grad()
        net.zero_hidden()
        optimizer.zero_grad()

        correction = net.forward(x)
        sim_prediction = Variable(data["state_next_sim"])
        if CUDA:
            sim_prediction = sim_prediction.cuda()

        loss = loss_function(sim_prediction + correction, y)
        loss.backward()

        optimizer.step()

        loss_episode = loss.clone().cpu().data.numpy()[0]
        diff_episode = F.mse_loss(x[:, :, :6], y).clone().cpu().data.numpy()[0]
        # printEpisodeLoss(epoch, epi, loss_episode, diff_episode, 100)
        # viz.update(epoch*train_data.num_examples+epi, loss_episode, "loss")
        # viz.update(epoch*train_data.num_examples+epi, diff_episode, "diff")

        loss_epoch.append(loss_episode)
        diff_epoch.append(diff_episode)
        loss.detach_()
        net.hidden[0].detach_()
        net.hidden[1].detach_()

    # Validation step
    loss_valid = []
    for j, data in enumerate(dataloader_test):
        x, y = makeIntoVariables(data)
        net.zero_hidden()
        correction = net.forward(x)
        sim_prediction = Variable(data["state_next_sim"])
        if CUDA:
            sim_prediction = sim_prediction.cuda()

        loss = loss_function(sim_prediction + correction, y)
        # if j == 10:
        #     print (sim_prediction)
        #     print (correction)
        #     print (y)

        loss_valid.append(loss.clone().cpu().data.numpy()[0])
    # viz.update(epoch*train_data.num_examples, loss_valid, "validation loss")

    printEpochLoss(epoch, np.mean(loss_valid), np.mean(loss_epoch), np.mean(diff_epoch))

    if TRAIN:
        saveModel(
            state=net.state_dict(),
            epoch=epoch,
            episode_idx=epi,
            loss_epoch=loss_epoch,
            diff_epoch=diff_epoch,
            is_best=(loss_valid < loss_min)
        )
        loss_min = min(loss_valid, loss_min)
    else:
        print(old_model_string)
        break

# Cleanup and mark that the experiment successfully completed
if hyperdash_support:
    exp.end()
