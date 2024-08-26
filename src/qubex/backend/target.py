from __future__ import annotations

import re
from enum import Enum
from typing import Union

from pydantic.dataclasses import dataclass
from .control_system import CapChannel, GenChannel
from .quantum_system import Qubit, Resonator
from .model import Model


class TargetType(Enum):
    CTRL_GE = "CTRL_GE"
    CTRL_EF = "CTRL_EF"
    CTRL_CR = "CTRL_CR"
    READ = "READ"
    UNKNOWN = "UNKNOWN"


QuantumObject = Union[Qubit, Resonator]


@dataclass
class CapTarget(Model):
    label: str
    frequency: float
    object: QuantumObject
    channel: CapChannel
    type: TargetType

    @classmethod
    def new_read_target(
        cls,
        *,
        resonator: Resonator,
        channel: CapChannel,
    ) -> CapTarget:
        return cls(
            label=Target.read_label(resonator.label),
            object=resonator,
            frequency=resonator.frequency,
            channel=channel,
            type=TargetType.READ,
        )


@dataclass
class Target(Model):
    label: str
    frequency: float
    object: QuantumObject
    channel: GenChannel
    type: TargetType

    def __repr__(self) -> str:
        return f"Target(label={self.label}, frequency={self.frequency}, channel={self.channel.id}, object={self.object.label})"

    @property
    def qubit(self) -> str:
        if isinstance(self.object, Qubit):
            return self.object.label
        elif isinstance(self.object, Resonator):
            return self.object.qubit
        else:
            raise ValueError("Invalid quantum object.")

    @property
    def coarse_frequency(self) -> float:
        if isinstance(self.channel, GenChannel):
            return self.channel.coarse_frequency * 1e-9
        else:
            raise ValueError("Invalid channel.")

    @property
    def fine_frequency(self) -> float:
        if isinstance(self.channel, GenChannel):
            return self.channel.fine_frequency * 1e-9
        else:
            raise ValueError("Invalid channel.")

    @property
    def is_available(self) -> bool:
        return abs(self.frequency - self.fine_frequency) < 250 * 1e-3  # 250 MHz

    @property
    def is_ge(self) -> bool:
        return self.type == TargetType.CTRL_GE

    @property
    def is_ef(self) -> bool:
        return self.type == TargetType.CTRL_EF

    @property
    def is_cr(self) -> bool:
        return self.type == TargetType.CTRL_CR

    @property
    def is_read(self) -> bool:
        return self.type == TargetType.READ

    @classmethod
    def new_target(
        cls,
        *,
        label: str,
        frequency: float,
        object: QuantumObject,
        channel: GenChannel,
        type: TargetType = TargetType.UNKNOWN,
    ) -> Target:
        return cls(
            label=label,
            frequency=frequency,
            object=object,
            channel=channel,
            type=type,
        )

    @classmethod
    def new_ge_target(
        cls,
        *,
        qubit: Qubit,
        channel: GenChannel,
    ) -> Target:
        return cls(
            label=Target.ge_label(qubit.label),
            object=qubit,
            frequency=qubit.ge_frequency,
            channel=channel,
            type=TargetType.CTRL_GE,
        )

    @classmethod
    def new_ef_target(
        cls,
        *,
        qubit: Qubit,
        channel: GenChannel,
    ) -> Target:
        return cls(
            label=Target.ef_label(qubit.label),
            object=qubit,
            frequency=qubit.ef_frequency,
            channel=channel,
            type=TargetType.CTRL_EF,
        )

    @classmethod
    def new_cr_target(
        cls,
        *,
        control_qubit: Qubit,
        target_qubit: Qubit | None = None,
        channel: GenChannel,
    ) -> Target:
        if target_qubit is not None:
            return cls(
                label=f"{control_qubit.label}-{target_qubit.label}",
                frequency=target_qubit.ge_frequency,
                object=control_qubit,
                channel=channel,
                type=TargetType.CTRL_CR,
            )
        else:
            return cls(
                label=Target.cr_label(control_qubit.label),
                frequency=round(channel.fine_frequency * 1e-9, 6),
                object=control_qubit,
                channel=channel,
                type=TargetType.CTRL_CR,
            )

    @classmethod
    def new_read_target(
        cls,
        *,
        resonator: Resonator,
        channel: GenChannel,
    ) -> Target:
        return cls(
            label=Target.read_label(resonator.label),
            object=resonator,
            frequency=resonator.frequency,
            channel=channel,
            type=TargetType.READ,
        )

    @classmethod
    def qubit_label(
        cls,
        label: str,
    ) -> str:
        if match := re.match(r"^R(Q\d+)$", label):
            qubit_label = match.group(1)
        elif match := re.match(r"^(Q\d+)$", label):
            qubit_label = match.group(1)
        elif match := re.match(r"^(Q\d+)-ef$", label):
            qubit_label = match.group(1)
        elif match := re.match(r"^(Q\d+)-CR$", label):
            qubit_label = match.group(1)
        elif match := re.match(r"^(Q\d+)-(Q\d+)$", label):
            qubit_label = match.group(1)
        elif match := re.match(r"^(Q\d+)(-|_)[a-zA-Z0-9]+$", label):
            qubit_label = match.group(1)
        else:
            raise ValueError(f"Invalid target label `{label}`.")
        return qubit_label

    @classmethod
    def ge_label(cls, label: str) -> str:
        qubit = cls.qubit_label(label)
        return f"{qubit}"

    @classmethod
    def ef_label(cls, label: str) -> str:
        qubit = cls.qubit_label(label)
        return f"{qubit}-ef"

    @classmethod
    def cr_label(cls, label: str) -> str:
        qubit = cls.qubit_label(label)
        return f"{qubit}-CR"

    @classmethod
    def read_label(cls, label: str) -> str:
        qubit = cls.qubit_label(label)
        return f"R{qubit}"