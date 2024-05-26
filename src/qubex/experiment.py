from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Final, Optional

import numpy as np
import plotly.graph_objects as go
from IPython.display import clear_output
from numpy.typing import NDArray
from rich.console import Console
from rich.table import Table

from . import fitting as fit
from . import visualization as viz
from .config import Config, Params, Qubit, Resonator, Target
from .experiment_tool import ExperimentTool
from .fitting import RabiParam
from .hardware import Box
from .measurement import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONTROL_WINDOW,
    DEFAULT_INTERVAL,
    DEFAULT_SHOTS,
    Measurement,
    MeasureResult,
)
from .pulse import Rect, Waveform

console = Console()

MIN_DURATION = 128


@dataclass
class SweepResult:
    """
    Data class representing the result of a sweep experiment.

    Attributes
    ----------
    qubit : str
        Identifier of the qubit.
    sweep_range : NDArray
        Sweep range of the experiment.
    data : NDArray
        Measured data.
    created_at : str
        Time when the experiment is conducted.
    """

    qubit: str
    sweep_range: NDArray
    data: NDArray
    created_at: str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def rotated(self, param: RabiParam) -> NDArray:
        return self.data * np.exp(-1j * param.angle)

    def normalized(self, param: RabiParam) -> NDArray:
        values = self.data * np.exp(-1j * param.angle)
        values_normalized = (values.imag - param.offset) / param.amplitude
        return values_normalized

    def plot(self, rabi_params: RabiParam):
        values = self.normalized(rabi_params)
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=self.sweep_range,
                y=values,
                mode="lines+markers",
                marker=dict(symbol="circle", size=8, color="#636EFA"),
                line=dict(width=1, color="grey", dash="dash"),
            )
        )
        fig.update_layout(
            title=f"Rabi oscillation of {self.qubit}",
            xaxis_title="Sweep value",
            yaxis_title="Normalized value",
            width=600,
        )
        fig.show()


class Experiment:
    """
    Class representing an experiment.

    Parameters
    ----------
    chip_id : str
        Identifier of the quantum chip.
    qubits : list[str]
        List of qubits to use in the experiment.
    data_dir : str, optional
        Path to the directory where the experiment data is stored. Defaults to "./data".
    """

    def __init__(
        self,
        *,
        chip_id: str,
        qubits: list[str],
        config_dir: str = DEFAULT_CONFIG_DIR,
    ):
        self._chip_id: Final = chip_id
        self._qubits: Final = qubits
        self._config: Final = Config(config_dir)
        self._measurement: Final = Measurement(
            chip_id=chip_id,
            config_dir=config_dir,
        )
        self.tool: Final = ExperimentTool(
            chip_id=chip_id,
            config_dir=config_dir,
        )
        self.system: Final = self._config.get_quantum_system(chip_id)
        self.print_resources()

    def print_resources(self):
        console.print("The following resources will be used:\n")
        table = Table(header_style="bold")
        table.add_column("ID", justify="left")
        table.add_column("NAME", justify="left")
        table.add_column("ADDRESS", justify="left")
        table.add_column("ADAPTER", justify="left")
        for box in self.boxes.values():
            table.add_row(box.id, box.name, box.address, box.adapter)
        console.print(table)

    @property
    def chip_id(self) -> str:
        """Get the chip ID."""
        return self._chip_id

    @property
    def qubits(self) -> dict[str, Qubit]:
        all_qubits = self._config.get_qubits(self._chip_id)
        return {
            qubit.label: qubit for qubit in all_qubits if qubit.label in self._qubits
        }

    @property
    def params(self) -> Params:
        """Get the system parameters."""
        return self._config.get_params(self._chip_id)

    @property
    def resonators(self) -> dict[str, Resonator]:
        all_resonators = self._config.get_resonators(self._chip_id)
        return {
            resonator.qubit: resonator
            for resonator in all_resonators
            if resonator.qubit in self._qubits
        }

    @property
    def targets(self) -> dict[str, Target]:
        all_targets = self._config.get_all_targets(self._chip_id)
        targets = [target for target in all_targets if target.qubit in self._qubits]
        return {target.label: target for target in targets}

    @property
    def boxes(self) -> dict[str, Box]:
        boxes = self._config.get_boxes_by_qubits(self._chip_id, self._qubits)
        return {box.id: box for box in boxes}

    def connect(self) -> None:
        """Connect to the backend."""
        box_list = list(self.boxes.keys())
        self._measurement.connect(box_list)

    def measure(
        self,
        sequence: dict[str, NDArray[np.complex128]],
        *,
        shots: int = DEFAULT_SHOTS,
        interval: int = DEFAULT_INTERVAL,
        control_window: int = DEFAULT_CONTROL_WINDOW,
        plot: bool = False,
    ) -> MeasureResult:
        """
        Measures the signals using the given sequence.

        Parameters
        ----------
        sequence : dict[str, NDArray[np.complex128]]
            Sequence of the experiment.
        shots : int, optional
            Number of shots. Defaults to DEFAULT_SHOTS.
        interval : int, optional
            Interval between shots. Defaults to DEFAULT_INTERVAL.
        control_window : int, optional
            Control window. Defaults to DEFAULT_CONTROL_WINDOW.
        plot : bool, optional
            Whether to plot the measured signals. Defaults to False.

        Returns
        -------
        MeasureResult
            Result of the experiment.
        """
        waveforms = {
            qubit: np.array(waveform, dtype=np.complex128)
            for qubit, waveform in sequence.items()
        }
        result = self._measurement.measure(
            waveforms=waveforms,
            shots=shots,
            interval=interval,
            control_window=control_window,
        )
        if plot:
            for qubit, data in result.raw.items():
                viz.plot_waveform(
                    data,
                    sampling_period=8,  # TODO: set dynamically
                    title=f"Raw signal of {qubit}",
                    xlabel="Capture time (ns)",
                    ylabel="Amplitude (arb. unit)",
                )
        return result

    def _measure_batch(
        self,
        sequences: list[dict[str, NDArray[np.complex128]]],
        *,
        shots: int = DEFAULT_SHOTS,
        interval: int = DEFAULT_INTERVAL,
        control_window: int = DEFAULT_CONTROL_WINDOW,
    ):
        """
        Measures the signals using the given sequences.

        Parameters
        ----------
        sequences : list[dict[str, NDArray[np.complex128]]]
            List of sequences to measure.
        shots : int, optional
            Number of shots. Defaults to DEFAULT_SHOTS.
        interval : int, optional
            Interval between shots. Defaults to DEFAULT_INTERVAL.
        control_window : int, optional
            Control window. Defaults to DEFAULT_CONTROL_WINDOW.

        Yields
        ------
        MeasureResult
            Result of the experiment.
        """
        waveforms_list = [
            {
                qubit: np.array(waveform, dtype=np.complex128)
                for qubit, waveform in sequence.items()
            }
            for sequence in sequences
        ]
        return self._measurement.measure_batch(
            waveforms_list=waveforms_list,
            shots=shots,
            interval=interval,
            control_window=control_window,
        )

    def rabi_experiment(
        self,
        *,
        time_range: NDArray,
        amplitudes: dict[str, float],
        shots: int = DEFAULT_SHOTS,
        interval: int = DEFAULT_INTERVAL,
        plot: bool = True,
    ) -> dict[str, SweepResult]:
        """
        Conducts a Rabi experiment.

        Parameters
        ----------
        time_range : NDArray
            Time range of the experiment.
        amplitudes : dict[str, float]
            Amplitudes of the control pulses.
        shots : int, optional
            Number of shots. Defaults to DEFAULT_SHOTS.
        interval : int, optional
            Interval between shots. Defaults to DEFAULT_INTERVAL.
        plot : bool, optional
            Whether to plot the measured signals. Defaults to True.

        Returns
        -------
        dict[str, SweepResult]
            Result of the experiment.
        """
        qubits = list(amplitudes.keys())
        time_range = np.array(time_range, dtype=np.int64)
        control_window = MIN_DURATION * (max(time_range) // MIN_DURATION + 1)
        waveforms_list = [
            {
                qubit: Rect(
                    duration=T,
                    amplitude=amplitudes[qubit],
                ).values
                for qubit in qubits
            }
            for T in time_range
        ]
        generator = self._measurement.measure_batch(
            waveforms_list=waveforms_list,
            shots=shots,
            interval=interval,
            control_window=control_window,
        )

        signals = defaultdict(list)
        for result in generator:
            for qubit, data in result.kerneled.items():
                signals[qubit].append(data)
            if plot:
                clear_output(wait=True)
                viz.scatter_iq_data(signals)
        results = {
            qubit: SweepResult(
                qubit=qubit,
                sweep_range=time_range,
                data=np.array(values),
            )
            for qubit, values in signals.items()
        }
        return results

    def sweep_parameter(
        self,
        *,
        param_range: NDArray,
        sequence: dict[str, Callable[..., Waveform]],
        pulse_count=1,
        shots: int = DEFAULT_SHOTS,
        interval: int = DEFAULT_INTERVAL,
        control_window: int = DEFAULT_CONTROL_WINDOW,
        plot: bool = True,
    ) -> dict[str, SweepResult]:
        """
        Sweeps a parameter and measures the signals.

        Parameters
        ----------
        param_range : NDArray
            Range of the parameter to sweep.
        sequence : dict[str, Callable[..., Waveform]]
            Parametric sequence to sweep.
        pulse_count : int, optional
            Number of pulses to apply. Defaults to 1.
        shots : int, optional
            Number of shots. Defaults to DEFAULT_SHOTS.
        interval : int, optional
            Interval between shots. Defaults to DEFAULT_INTERVAL.
        control_window : int, optional
            Control window. Defaults to DEFAULT_CONTROL_WINDOW.
        plot : bool, optional
            Whether to plot the measured signals. Defaults to True.

        Returns
        -------
        dict[str, SweepResult]
            Result of the experiment.
        """
        qubits = list(sequence.keys())
        sequences = [
            {
                qubit: sequence[qubit](param).repeated(pulse_count).values
                for qubit in qubits
            }
            for param in param_range
        ]
        generator = self._measure_batch(
            sequences=sequences,
            shots=shots,
            interval=interval,
            control_window=control_window,
        )
        signals = defaultdict(list)
        for result in generator:
            for qubit, data in result.kerneled.items():
                signals[qubit].append(data)
            if plot:
                viz.scatter_iq_data(signals)
        results = {
            qubit: SweepResult(
                qubit=qubit,
                sweep_range=param_range,
                data=np.array(values),
            )
            for qubit, values in signals.items()
        }
        return results

    def rabi_check(
        self,
        qubits: list[str],
        *,
        time_range: NDArray = np.arange(0, 201, 10),
        shots: int = DEFAULT_SHOTS,
        interval: int = DEFAULT_INTERVAL,
    ) -> dict[str, SweepResult]:
        """
        Conducts a Rabi experiment with the default amplitude.

        Parameters
        ----------
        qubits : list[str]
            List of qubits to check the Rabi oscillation.
        time_range : NDArray, optional
            Time range of the experiment. Defaults to np.arange(0, 201, 10).
        shots : int, optional
            Number of shots. Defaults to DEFAULT_SHOTS.
        interval : int, optional
            Interval between shots. Defaults to DEFAULT_INTERVAL.

        Returns
        -------
        dict[str, SweepResult]
            Result of the experiment.
        """
        ampl = self.params.control_amplitude
        amplitudes = {qubit: ampl[qubit] for qubit in qubits}
        result = self.rabi_experiment(
            amplitudes=amplitudes,
            time_range=time_range,
            shots=shots,
            interval=interval,
        )
        return result

    def repeat_sequence(
        self,
        *,
        sequence: dict[str, Waveform],
        n: int,
        shots: int = DEFAULT_SHOTS,
        interval: int = DEFAULT_INTERVAL,
        plot: bool = True,
    ) -> dict[str, SweepResult]:
        """
        Repeats the pulse sequence n times.

        Parameters
        ----------
        sequence : dict[str, Waveform]
            Pulse sequence to repeat.
        n : int
            Number of times to repeat the pulse.
        shots : int, optional
            Number of shots. Defaults to DEFAULT_SHOTS.
        interval : int, optional
            Interval between shots. Defaults to DEFAULT_INTERVAL.
        plot : bool, optional
            Whether to plot the measured signals. Defaults to True.

        Returns
        -------
        dict[str, SweepResult]
            Result of the experiment.
        """
        repeated_sequence = {
            qubit: lambda param, p=pulse: p.repeated(int(param))
            for qubit, pulse in sequence.items()
        }
        result = self.sweep_parameter(
            param_range=np.arange(n + 1),
            sequence=repeated_sequence,
            pulse_count=1,
            shots=shots,
            interval=interval,
        )
        return result

    def normalize(
        self,
        value: complex,
        param: RabiParam,
    ) -> float:
        """
        Normalizes the measured I/Q value.

        Parameters
        ----------
        value : complex
            Measured I/Q value.
        param : RabiParam
            Parameters of the Rabi oscillation.

        Returns
        -------
        float
            Normalized value.
        """
        value_rotated = value * np.exp(-1j * param.angle)
        value_normalized = (value_rotated.imag - param.offset) / param.amplitude
        return value_normalized

    def fit_rabi(
        self,
        sweep_result: SweepResult,
        wave_count: Optional[float] = None,
    ) -> RabiParam:
        """
        Fits the measured data to a Rabi oscillation.

        Parameters
        ----------
        sweep_result : SweepResult
            Result of the Rabi experiment.
        wave_count : float, optional
            Number of waves in sweep_result. Defaults to None.

        Returns
        -------
        RabiParam
            Parameters of the Rabi oscillation.
        """
        rabi_param = fit.fit_rabi(
            qubit=sweep_result.qubit,
            times=sweep_result.sweep_range,
            data=sweep_result.data,
            wave_count=wave_count,
            is_damped=False,
        )
        return rabi_param

    def fit_damped_rabi(
        self,
        sweep_result: SweepResult,
        wave_count: Optional[float] = None,
    ) -> RabiParam:
        """
        Fits the measured data to a damped Rabi oscillation.

        Parameters
        ----------
        sweep_result : SweepResult
            Result of the Rabi experiment.
        wave_count : float, optional
            Number of waves in sweep_result. Defaults to None.

        Returns
        -------
        RabiParam
            Parameters of the Rabi oscillation.
        """
        rabi_param = fit.fit_rabi(
            qubit=sweep_result.qubit,
            times=sweep_result.sweep_range,
            data=sweep_result.data,
            wave_count=wave_count,
            is_damped=True,
        )
        return rabi_param
