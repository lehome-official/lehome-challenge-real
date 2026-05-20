"""
Standalone protocol helpers — no lerobot install required.

Provides the data classes used to exchange observations and actions
between the robot client and the policy server via gRPC.

Observation flow (robot → server)
----------------------------------
The robot client wraps each observation in a TimedObservation and pickles it
before sending via SendObservations.  The .observation dict has these keys:

    State (float, one per motor):
        left_shoulder_pan.pos   left_shoulder_lift.pos  left_elbow_flex.pos
        left_wrist_flex.pos     left_wrist_roll.pos     left_gripper.pos
        right_shoulder_pan.pos  right_shoulder_lift.pos right_elbow_flex.pos
        right_wrist_flex.pos    right_wrist_roll.pos    right_gripper.pos

    Images (numpy uint8 arrays, RGB):
        left_wrist   shape (480, 640, 3)
        right_wrist  shape (480, 640, 3)
        right_front  shape (720, 1280, 3)

    Task string:
        task         str

Action flow (server → robot)
------------------------------
The server returns a list[TimedAction] pickled into Actions.data.
Each TimedAction.action must be a torch.Tensor of shape (12,), where index
order matches MOTOR_NAMES below.

MOTOR_NAMES = [
    "left_shoulder_pan.pos",  "left_shoulder_lift.pos", "left_elbow_flex.pos",
    "left_wrist_flex.pos",    "left_wrist_roll.pos",    "left_gripper.pos",
    "right_shoulder_pan.pos", "right_shoulder_lift.pos","right_elbow_flex.pos",
    "right_wrist_flex.pos",   "right_wrist_roll.pos",   "right_gripper.pos",
]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TimedData:
    timestamp: float   # Unix time (time.time())
    timestep:  int

    def get_timestamp(self) -> float: return self.timestamp
    def get_timestep(self)  -> int:   return self.timestep


@dataclass
class TimedAction(TimedData):
    """A single action with timing information.  action must be torch.Tensor (12,)."""
    action: Any  # torch.Tensor shape (12,)

    def get_action(self): return self.action


@dataclass
class TimedObservation(TimedData):
    """A single observation from the robot."""
    observation: dict[str, Any]
    must_go: bool = False

    def get_observation(self) -> dict[str, Any]: return self.observation


@dataclass
class RemotePolicyConfig:
    """Sent by the robot client during handshake.  Servers may inspect or ignore."""
    policy_type:              str
    pretrained_name_or_path:  str
    lerobot_features:         dict
    actions_per_chunk:        int
    device:                   str  = "cpu"
    rename_map:               dict = field(default_factory=dict)
