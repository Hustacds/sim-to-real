from mujoco_py.mjtypes import POINTER, c_double
from rllab.algos.trpo import TRPO
from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.envs.gym_env import GymEnv
from rllab.envs.normalized_env import normalize
from rllab.policies.gaussian_mlp_policy import GaussianMLPPolicy
from rllab.misc.instrument import run_experiment_lite

from buffer_ import Buffer, FIFO

## Definiing the environnement
coeff = 0.85

env = normalize(GymEnv('Swimmer-v1', force_reset=True), normalize_obs=True)
env2 = normalize(GymEnv('Swimmer-v1', force_reset=True), normalize_obs=True)

# The second environnement models the real world
#env2.env.model.opt.gravity = np.array([0, 0, -9.81*coeff]).ctypes.data_as(POINTER(c_double*3)).contents
env2.wrapped_env.env.env.model.opt.gravity = np.array([0, 0, -9.81*coeff]).ctypes.data_as(POINTER(c_double*3)).contents


## Defining the buffer
observation_dim = int(env.observation_space.shape[0])
action_dim = int(env.action_space.shape[0])
rng = np.random.RandomState(seed=23)
max_steps = 10000
history = 0

buffer_ = Buffer(observation_dim, action_dim, rng, history, max_steps)
prev_observations = FIFO(history)
actions = FIFO(history+1)  # also taking current action

for i_episode in range(1000):
    observation = env.reset()
    observation2 = env2.reset()
    match_env(env, env2)
    prev_observations.push(observation)

    for t in range(100):
        # env.render()
        # env2.render()

        action = env.action_space.sample()
        observation, reward, done, info = env.step(action)
        observation2, reward2, done2, info2 = env2.step(action)

        actions.push(action)
        if len(prev_observations) == history and len(actions) == history+1:
            buffer_.add_sample(prev_observations.copy(), actions.copy(), observation, observation2, reward, reward2)
        prev_observations.push(observation2)
        match_env(env, env2)

        if done:
            print("Episode finished after {} timesteps".format(t+1))
            prev_observations.clear()
            actions.clear()
            break
buffer_.save('/Tmp/alitaiga/sim-to-real/buffer-test')
# buffer_ = Buffer.load('/Tmp/alitaiga/sim-to-real/buffer-test')

def run_task(*_):
    policy = GaussianMLPPolicy(
        env_spec=env.spec,
        # The neural network policy should have two hidden layers, each with 32 hidden units.
        hidden_sizes=(50, 50)
    )

    baseline = LinearFeatureBaseline(env_spec=env.spec)

    algo = TRPO(
        env=env,
        policy=policy,
        baseline=baseline,
        batch_size=4000,
        whole_paths=True,
        max_path_length=100,
        n_itr=40,
        discount=0.99,
        step_size=0.01,
    )
    algo.train()

run_experiment_lite(
    run_task,
    # Number of parallel workers for sampling
    n_parallel=1,
    # Only keep the snapshot parameters for the last iteration
    snapshot_mode="last",
    # Specifies the seed for the experiment. If this is not provided, a random seed
    # will be used
    seed=1,
    #plot=True,
)
