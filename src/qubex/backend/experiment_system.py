from __future__ import annotations

from typing import Final, Literal, Sequence

import numpy as np
from pydantic.dataclasses import dataclass

from .control_system import (
    Box,
    CapChannel,
    CapPort,
    ControlSystem,
    GenChannel,
    GenPort,
    PortType,
)
from .model import Model
from .quantum_system import Chip, Mux, QuantumSystem, Qubit, Resonator
from .target import Target

DEFAULT_CONTROL_AMPLITUDE: Final = 0.03
DEFAULT_READOUT_AMPLITUDE: Final = 0.01
DEFAULT_CONTROL_VATT: Final = 3072
DEFAULT_READOUT_VATT: Final = 2048
DEFAULT_CONTROL_FSC: Final = 40527
DEFAULT_READOUT_FSC: Final = 40527
DEFAULT_CAPTURE_DELAY: Final = 7


@dataclass
class WiringInfo(Model):
    ctrl: list[tuple[Qubit, GenPort]]
    read_out: list[tuple[Mux, GenPort]]
    read_in: list[tuple[Mux, CapPort]]


@dataclass
class QubitPortSet(Model):
    ctrl_port: GenPort
    read_out_port: GenPort
    read_in_port: CapPort


@dataclass
class ControlParams(Model):
    control_amplitude: dict[str, float]
    readout_amplitude: dict[str, float]
    control_vatt: dict[str, int]
    readout_vatt: dict[int, int]
    control_fsc: dict[str, int]
    readout_fsc: dict[int, int]
    capture_delay: dict[int, int]

    def get_control_amplitude(self, qubit: str) -> float:
        return self.control_amplitude.get(qubit, DEFAULT_CONTROL_AMPLITUDE)

    def get_readout_amplitude(self, qubit: str) -> float:
        return self.readout_amplitude.get(qubit, DEFAULT_READOUT_AMPLITUDE)

    def get_control_vatt(self, qubit: str) -> int:
        return self.control_vatt.get(qubit, DEFAULT_CONTROL_VATT)

    def get_readout_vatt(self, mux: int) -> int:
        return self.readout_vatt.get(mux, DEFAULT_READOUT_VATT)

    def get_control_fsc(self, qubit: str) -> int:
        return self.control_fsc.get(qubit, DEFAULT_CONTROL_FSC)

    def get_readout_fsc(self, mux: int) -> int:
        return self.readout_fsc.get(mux, DEFAULT_READOUT_FSC)

    def get_capture_delay(self, mux: int) -> int:
        return self.capture_delay.get(mux, DEFAULT_CAPTURE_DELAY)


class ExperimentSystem:
    def __init__(
        self,
        quantum_system: QuantumSystem,
        control_system: ControlSystem,
        wiring_info: WiringInfo,
        control_params: ControlParams,
    ):
        self._quantum_system: Final = quantum_system
        self._control_system: Final = control_system
        self._wiring_info: Final = wiring_info
        self._control_params: Final = control_params
        self._qubit_port_set_map: Final = self._create_qubit_port_set_map()
        self._initialize_system()
        self._initialize_targets()

    @property
    def hash(self) -> int:
        return hash(
            (
                self.quantum_system.hash,
                self.control_system.hash,
                self.wiring_info.hash,
                self.control_params.hash,
            )
        )

    @property
    def quantum_system(self) -> QuantumSystem:
        return self._quantum_system

    @property
    def control_system(self) -> ControlSystem:
        return self._control_system

    @property
    def wiring_info(self) -> WiringInfo:
        return self._wiring_info

    @property
    def control_params(self) -> ControlParams:
        return self._control_params

    @property
    def chip(self) -> Chip:
        return self.quantum_system.chip

    @property
    def qubits(self) -> list[Qubit]:
        return self.quantum_system.qubits

    @property
    def resonators(self) -> list[Resonator]:
        return self.quantum_system.resonators

    @property
    def boxes(self) -> list[Box]:
        return self.control_system.boxes

    @property
    def ge_targets(self) -> list[Target]:
        return list(self._ge_target_dict.values())

    @property
    def ef_targets(self) -> list[Target]:
        return list(self._ef_target_dict.values())

    @property
    def cr_targets(self) -> list[Target]:
        return list(self._cr_target_dict.values())

    @property
    def control_targets(self) -> list[Target]:
        return self.ge_targets + self.ef_targets + self.cr_targets

    @property
    def readout_targets(self) -> list[Target]:
        return list(self._readout_target_dict.values())

    @property
    def targets(self) -> list[Target]:
        return (
            self.ge_targets + self.ef_targets + self.cr_targets + self.readout_targets
        )

    @property
    def target_gen_channel_map(self) -> dict[Target, GenChannel]:
        return self._target_gen_channel_map

    @property
    def target_cap_channel_map(self) -> dict[Target, CapChannel]:
        return self._target_cap_channel_map

    def get_mux(self, label: int | str) -> Mux:
        return self.quantum_system.get_mux(label)

    def get_qubit(self, label: int | str) -> Qubit:
        return self.quantum_system.get_qubit(label)

    def get_resonator(self, label: int | str) -> Resonator:
        return self.quantum_system.get_resonator(label)

    def get_spectator_qubits(self, qubit: int | str) -> list[Qubit]:
        return self.quantum_system.get_spectator_qubits(qubit)

    def get_box(self, box_id: str) -> Box:
        return self.control_system.get_box(box_id)

    def get_boxes_for_qubits(self, qubits: Sequence[str]) -> list[Box]:
        box_ids = set()
        for qubit in qubits:
            ports = self.get_qubit_port_set(qubit)
            if ports is None:
                continue
            box_ids.add(ports.ctrl_port.box_id)
            box_ids.add(ports.read_out_port.box_id)
            box_ids.add(ports.read_in_port.box_id)
        return [self.get_box(box_id) for box_id in box_ids]

    def get_target(self, label: str) -> Target:
        try:
            return self._target_dict[label]
        except KeyError:
            raise KeyError(f"Target `{label}` not found.") from None

    def get_ge_target(self, label: str) -> Target:
        label = Target.ge_label(label)
        return self.get_target(label)

    def get_ef_target(self, label: str) -> Target:
        label = Target.ef_label(label)
        return self.get_target(label)

    def get_cr_target(self, label: str) -> Target:
        label = Target.cr_label(label)
        return self.get_target(label)

    def get_readout_target(self, label: str) -> Target:
        label = Target.readout_label(label)
        return self.get_target(label)

    def get_qubit_port_set(self, qubit: int | str) -> QubitPortSet | None:
        if isinstance(qubit, int):
            qubit = self.qubits[qubit].label
        return self._qubit_port_set_map.get(qubit)

    def get_control_port(self, qubit: int | str) -> GenPort:
        ports = self.get_qubit_port_set(qubit)
        if ports is None:
            raise ValueError(f"Qubit `{qubit}` not found.")
        return ports.ctrl_port

    def get_base_frequency(self, label: str) -> float:
        target = self.get_target(label)
        channel = self.target_gen_channel_map[target]
        port = self.control_system.get_port_by_id(channel.port_id)
        if isinstance(port, GenPort):
            return round(port.base_frequencies[channel.number] * 1e-9, 10)
        raise ValueError("Port is not a GenPort.")

    def get_diff_frequency(self, label: str) -> float:
        target = self.get_target(label)
        return round(target.frequency - self.get_base_frequency(label), 10)

    def get_mux_by_readout_port(self, port: GenPort | CapPort) -> Mux | None:
        if isinstance(port, CapPort):
            for mux, cap_port in self.wiring_info.read_in:
                if cap_port == port:
                    return mux
        elif isinstance(port, GenPort):
            for mux, gen_port in self.wiring_info.read_out:
                if gen_port == port:
                    return mux
        return None

    def get_qubit_by_control_port(self, port: GenPort) -> Qubit | None:
        for qubit, gen_port in self.wiring_info.ctrl:
            if gen_port == port:
                return qubit
        return None

    def get_readout_pair(self, port: CapPort) -> GenPort:
        cap_mux = self.get_mux_by_readout_port(port)
        if cap_mux is None:
            raise ValueError(f"No mux found for port: {port}")
        for gen_mux, gen_port in self.wiring_info.read_out:
            if gen_mux.index == cap_mux.index:
                return gen_port
        raise ValueError(f"No readout pair found for port: {port}")

    def find_readout_lo_nco(
        self,
        mux: Mux,
        *,
        lo_min: int = 8_000_000_000,
        lo_max: int = 11_000_000_000,
        lo_step: int = 500_000_000,
        nco_step: int = 23_437_500,
        cnco: int = 1_500_000_000,
        fnco_min: int = -234_375_000,
        fnco_max: int = +234_375_000,
    ) -> tuple[int, int, int]:
        """
        Finds the (lo, cnco, fnco) values for the readout mux.

        Parameters
        ----------
        mux : Mux
            The readout mux.
        lo_min : int, optional
            The minimum LO frequency, by default 8_000_000_000.
        lo_max : int, optional
            The maximum LO frequency, by default 11_000_000_000.
        lo_step : int, optional
            The LO frequency step, by default 500_000_000.
        nco_step : int, optional
            The NCO frequency step, by default 23_437_500.
        cnco : int, optional
            The CNCO frequency, by default 2_250_000_000.
        fnco_min : int, optional
            The minimum FNCO frequency, by default -750_000_000.
        fnco_max : int, optional
            The maximum FNCO frequency, by default +750_000_000.

        Returns
        -------
        tuple[int, int, int]
            The tuple (lo, cnco, fnco) for the readout mux.
        """
        frequencies = [resonator.frequency * 1e9 for resonator in mux.resonators]
        target_frequency = (max(frequencies) + min(frequencies)) / 2

        min_diff = float("inf")
        best_lo = None
        best_fnco = None

        for lo in range(lo_min, lo_max + 1, lo_step):
            for fnco in range(fnco_min, fnco_max + 1, nco_step):
                current_value = lo + cnco + fnco
                current_diff = abs(current_value - target_frequency)
                if current_diff < min_diff:
                    min_diff = current_diff
                    best_lo = lo
                    best_fnco = fnco
        if best_lo is None or best_fnco is None:
            raise ValueError("No valid (lo, fnco) pair found.")
        return best_lo, cnco, best_fnco

    def find_control_lo_nco(
        self,
        qubit: Qubit,
        n_channels: int,
        *,
        mandatory: Sequence[Literal["ge", "ef"]] | None = None,
        lo_min: int = 8_000_000_000,
        lo_max: int = 11_000_000_000,
        lo_step: int = 500_000_000,
        nco_step: int = 23_437_500,
        cnco: int = 2_250_000_000,
        fnco_min: int = -750_000_000,
        fnco_max: int = +750_000_000,
        max_diff: int = 1_500_000_000,
    ) -> tuple[int, int, tuple[int, int, int]]:
        """
        Finds the (lo, cnco, (fnco_ge, fnco_ef, fnco_cr)) values for the control qubit.

        Parameters
        ----------
        qubit : Qubit
            The control qubit.
        n_channels : int
            The number of channels.
        lo_min : int, optional
            The minimum LO frequency, by default 8_000_000_000.
        lo_max : int, optional
            The maximum LO frequency, by default 11_000_000_000.
        lo_step : int, optional
            The LO frequency step, by default 500_000_000.
        nco_step : int, optional
            The NCO frequency step, by default 23_437_500.
        cnco : int, optional
            The CNCO frequency, by default 2_250_000_000.
        fnco_min : int, optional
            The minimum FNCO frequency, by default -750_000_000.
        fnco_max : int, optional
            The maximum FNCO frequency, by default +750_000_000.
        max_diff : int, optional
            The maximum difference between frequencies, by default 1_500_000_000.

        Returns
        -------
        tuple[int, int, tuple[int, int, int]]
            The tuple (lo, cnco, (fnco_ge, fnco_ef, fnco_cr)) for the control qubit.
        """

        f = {
            "ge": self.get_qubit(qubit.label).ge_frequency * 1e9,
            "ef": self.get_qubit(qubit.label).ef_frequency * 1e9,
            "CR": self._calc_cr_target_frequency(qubit) * 1e9,
        }

        if n_channels == 1:
            f_target = f["ge"]
        elif n_channels == 3:
            f_spectators = [
                spectator.ge_frequency * 1e9
                for spectator in self.get_spectator_qubits(qubit.label)
                if spectator.ge_frequency > 0
            ]
            if mandatory is None:
                mandatory = ["ge"]
            mandatory_frequencies = [f[label] for label in mandatory]
            frequencies = mandatory_frequencies + f_spectators
            f_target = self.find_optimal_center_frequency(
                frequencies=frequencies,
                max_diff=max_diff,
                mandatory_frequencies=mandatory_frequencies,
            )
        else:
            raise ValueError("Invalid number of channels: ", n_channels)

        min_diff = float("inf")
        best_lo = None
        for lo in range(lo_min, lo_max + 1, lo_step):
            current_value = lo - cnco
            current_diff = abs(current_value - f_target)
            if current_diff < min_diff:
                min_diff = current_diff
                best_lo = lo
        if best_lo is None:
            raise ValueError("No valid lo value found for: ", f_target)

        def find_fnco(target_frequency: float):
            min_diff = float("inf")
            best_fnco = None
            for fnco in range(fnco_min, fnco_max + 1, nco_step):
                current_value = abs(best_lo - cnco - fnco)
                current_diff = abs(current_value - target_frequency)
                if current_diff < min_diff:
                    min_diff = current_diff
                    best_fnco = fnco
            if best_fnco is None:
                raise ValueError("No valid fnco value found for: ", target_frequency)
            return best_fnco

        fnco_ge = find_fnco(f["ge"])

        if n_channels == 1:
            return best_lo, cnco, (fnco_ge, 0, 0)

        fnco_ef = find_fnco(f["ef"])
        fnco_cr = find_fnco(f["CR"])

        return best_lo, cnco, (fnco_ge, fnco_ef, fnco_cr)

    def find_optimal_center_frequency(
        self,
        frequencies: list[float],
        max_diff: float,
        *,
        mandatory_frequencies: list[float] | None = None,
    ) -> float:
        """
        Finds the optimal center frequency for the given frequencies.

        Parameters
        ----------
        frequencies : list[float]
            The list of frequencies.
        max_diff : float
            The maximum difference between the maximum and minimum frequencies.
        mandatory_frequencies : list[float], optional
            The list of mandatory frequencies, by default None.

        Returns
        -------
        float
            The optimal center frequency.
        """
        frequencies = [f for f in frequencies if f > 0]
        if not frequencies:
            return 0.0

        f_max = max(frequencies)
        f_min = min(frequencies)

        # case 1: all frequencies can be covered by the max_diff
        if f_max - f_min <= max_diff:
            return (f_max + f_min) / 2

        # case 2: find the frequency which covers the most frequencies
        d = max_diff * 0.5
        if mandatory_frequencies is not None:
            mf_min = min(mandatory_frequencies)
            mf_max = max(mandatory_frequencies)
            if mf_max - mf_min > max_diff:
                raise ValueError("Mandatory frequencies cannot be covered.")
            search_points = np.array([mf_max - d, mf_min + d])
        else:
            freqs = np.array(frequencies)
            search_points = np.concatenate([freqs - d, freqs + d])
        center_freqs_by_count = [
            (
                np.sum([1 for f in frequencies if p - d <= f <= p + d]),
                np.mean([f for f in frequencies if p - d <= f <= p + d] or [0]),
            )
            for p in search_points
        ]
        return float(max(center_freqs_by_count, key=lambda x: x[0])[1])

    def _calc_cr_target_frequency(
        self,
        qubit: Qubit,
        max_diff: float = 0.25,
    ) -> float:
        spectator_qubits = self.get_spectator_qubits(qubit.label)
        frequencies = [
            spectator.ge_frequency
            for spectator in spectator_qubits
            if spectator.ge_frequency > 0
        ]
        if not frequencies:
            return qubit.ge_frequency
        cr_frequency = self.find_optimal_center_frequency(frequencies, max_diff)
        return cr_frequency

    def _create_qubit_port_set_map(self) -> dict[str, QubitPortSet]:
        ctrl_port_map: dict[str, GenPort] = {}
        read_out_port_map: dict[str, GenPort] = {}
        read_in_port_map: dict[str, CapPort] = {}
        for qubit, gen_port in self.wiring_info.ctrl:
            ctrl_port_map[qubit.label] = gen_port
        for mux, gen_port in self.wiring_info.read_out:
            for resonator in mux.resonators:
                read_out_port_map[resonator.qubit] = gen_port
        for mux, cap_port in self.wiring_info.read_in:
            for resonator in mux.resonators:
                read_in_port_map[resonator.qubit] = cap_port
        return {
            qubit: QubitPortSet(
                ctrl_port=ctrl_port_map[qubit],
                read_out_port=read_out_port_map[qubit],
                read_in_port=read_in_port_map[qubit],
            )
            for qubit in ctrl_port_map
        }

    def _initialize_system(self):
        params = self.control_params
        for box in self.boxes:
            for port in box.ports:
                if isinstance(port, GenPort):
                    self._initialize_gen_port(port, params)
                elif isinstance(port, CapPort):
                    self._initialize_cap_port(port, params)

    def _initialize_gen_port(
        self,
        port: GenPort,
        params: ControlParams,
    ) -> None:
        port.rfswitch = "pass"
        if port.type == PortType.READ_OUT:
            mux = self.get_mux_by_readout_port(port)
            if mux is None:
                return
            lo, cnco, fnco = self.find_readout_lo_nco(mux=mux)
            port.lo_freq = lo
            port.cnco_freq = cnco
            port.sideband = "U"
            port.vatt = params.get_readout_vatt(mux.index)
            port.fullscale_current = params.get_readout_fsc(mux.index)
            port.channels[0].fnco_freq = fnco
        elif port.type == PortType.CTRL:
            qubit = self.get_qubit_by_control_port(port)
            if qubit is None:
                return
            lo, cnco, fncos = self.find_control_lo_nco(
                qubit=qubit,
                n_channels=port.n_channels,
            )
            port.lo_freq = lo
            port.cnco_freq = cnco
            port.sideband = "L"
            port.vatt = params.get_control_vatt(qubit.label)
            port.fullscale_current = params.get_control_fsc(qubit.label)
            for idx, gen_channel in enumerate(port.channels):
                gen_channel.fnco_freq = fncos[idx]

    def _initialize_cap_port(
        self,
        port: CapPort,
        params: ControlParams,
    ) -> None:
        port.rfswitch = "open"
        if port.type == PortType.READ_IN:
            mux = self.get_mux_by_readout_port(port)
            if mux is None:
                return
            lo, cnco, fnco = self.find_readout_lo_nco(mux=mux)
            port.lo_freq = lo
            port.cnco_freq = cnco
            for cap_channel in port.channels:
                cap_channel.fnco_freq = fnco
                cap_channel.ndelay = params.get_capture_delay(mux.index)

    def _initialize_targets(self) -> None:
        ge_target_dict: dict[str, Target] = {}
        ef_target_dict: dict[str, Target] = {}
        cr_target_dict: dict[str, Target] = {}
        readout_target_dict: dict[str, Target] = {}
        target_gen_channel_map: dict[Target, GenChannel] = {}
        target_cap_channel_map: dict[Target, CapChannel] = {}

        for box in self.boxes:
            for port in box.ports:
                # gen ports
                if isinstance(port, GenPort):
                    # ctrl ports
                    if port.type == PortType.CTRL:
                        qubit = self.get_qubit_by_control_port(port)
                        if qubit is None:
                            continue

                        if port.n_channels == 1:
                            # ge only
                            ge_target = Target.ge_target(
                                label=qubit.label,
                                frequency=qubit.ge_frequency,
                            )
                            ge_target_dict[ge_target.label] = ge_target
                            target_gen_channel_map[ge_target] = port.channels[0]
                        elif port.n_channels == 3:
                            # ge
                            ge_target = Target.ge_target(
                                label=qubit.label,
                                frequency=qubit.ge_frequency,
                            )
                            ge_target_dict[ge_target.label] = ge_target
                            ge_channel = port.channels[ge_target.channel_nuber]
                            target_gen_channel_map[ge_target] = ge_channel
                            # ef
                            ef_target = Target.ef_target(
                                label=qubit.label,
                                frequency=qubit.ef_frequency,
                            )
                            ef_target_dict[ef_target.label] = ef_target
                            ef_channel = port.channels[ef_target.channel_nuber]
                            target_gen_channel_map[ef_target] = ef_channel
                            # cr
                            cr_target = Target.cr_target(
                                label=qubit.label,
                                frequency=self._calc_cr_target_frequency(qubit),
                            )
                            cr_target_dict[cr_target.label] = cr_target
                            cr_channel = port.channels[cr_target.channel_nuber]
                            target_gen_channel_map[cr_target] = cr_channel
                    # readout ports
                    elif port.type == PortType.READ_OUT:
                        mux = self.get_mux_by_readout_port(port)
                        if mux is None:
                            continue
                        for resonator in mux.resonators:
                            readout_target = Target.readout_target(
                                label=resonator.label,
                                frequency=resonator.frequency,
                            )
                            readout_target_dict[readout_target.label] = readout_target
                            target_gen_channel_map[readout_target] = port.channels[0]
                # cap ports
                if isinstance(port, CapPort):
                    if port.type == PortType.READ_IN:
                        mux = self.get_mux_by_readout_port(port)
                        if mux is None:
                            continue
                        for idx, resonator in enumerate(mux.resonators):
                            readout_target = Target.readout_target(
                                label=resonator.label,
                                frequency=resonator.frequency,
                            )
                            target_cap_channel_map[readout_target] = port.channels[idx]

        self._ge_target_dict = dict(sorted(ge_target_dict.items()))
        self._ef_target_dict = dict(sorted(ef_target_dict.items()))
        self._cr_target_dict = dict(sorted(cr_target_dict.items()))
        self._readout_target_dict = dict(sorted(readout_target_dict.items()))
        self._target_dict = (
            self._ge_target_dict
            | self._ef_target_dict
            | self._cr_target_dict
            | self._readout_target_dict
        )
        self._target_gen_channel_map = dict(
            sorted(
                target_gen_channel_map.items(),
                key=lambda target: target[0].label,
            )
        )
        self._target_cap_channel_map = dict(
            sorted(
                target_cap_channel_map.items(),
                key=lambda target: target[0].label,
            )
        )
