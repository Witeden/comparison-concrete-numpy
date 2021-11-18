"""Module to hold a user friendly class to compile programs."""

from copy import deepcopy
from enum import Enum, unique
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from ..common.compilation import CompilationArtifacts, CompilationConfiguration
from ..common.data_types import Integer
from ..common.operator_graph import OPGraph
from ..common.representation.intermediate import IntermediateNode
from ..common.values import BaseValue
from .compile import compile_numpy_function_into_op_graph, measure_op_graph_bounds_and_update
from .np_dtypes_helpers import get_base_value_for_numpy_or_python_constant_data


@unique
class EncryptedStatus(str, Enum):
    """Enum to validate GenericFunction op_kind."""

    CLEAR = "clear"
    ENCRYPTED = "encrypted"


class NPFHECompiler:
    """Class to ease the conversion of a numpy program to its FHE equivalent."""

    INPUTSET_SIZE_BEFORE_AUTO_BOUND_UPDATE: int = 128

    # _function_to_compile is not optional but mypy has a long standing bug and is not able to
    # understand this properly. See https://github.com/python/mypy/issues/708#issuecomment-605636623
    _function_to_compile: Optional[Callable]
    _function_parameters_encrypted_status: Dict[str, bool]
    _current_inputset: List[Union[Any, Tuple]]
    _op_graph: Optional[OPGraph]
    _nodes_and_bounds: Dict[IntermediateNode, Dict[str, Any]]

    _compilation_configuration: CompilationConfiguration

    compilation_artifacts: CompilationArtifacts

    def __init__(
        self,
        function_to_compile: Callable,
        function_parameters_encrypted_status: Dict[str, Union[str, EncryptedStatus]],
        compilation_configuration: Optional[CompilationConfiguration] = None,
        compilation_artifacts: Optional[CompilationArtifacts] = None,
    ) -> None:
        self._function_to_compile = function_to_compile
        self._function_parameters_encrypted_status = {
            param_name: EncryptedStatus(status.lower()) == EncryptedStatus.ENCRYPTED
            for param_name, status in function_parameters_encrypted_status.items()
        }

        self._current_inputset = []
        self._op_graph = None
        self._nodes_and_bounds = {}

        self._compilation_configuration = (
            deepcopy(compilation_configuration)
            if compilation_configuration is not None
            else CompilationConfiguration()
        )
        self.compilation_artifacts = (
            compilation_artifacts if compilation_artifacts is not None else CompilationArtifacts()
        )

    @property
    def function_to_compile(self) -> Callable:
        """Get the function to compile.

        Returns:
            Callable: the function to compile.
        """
        # Continuation of mypy bug
        assert self._function_to_compile is not None
        return self._function_to_compile

    @property
    def op_graph(self) -> Optional[OPGraph]:
        """Return a copy of the OPGraph.

        Returns:
            Optional[OPGraph]: the held OPGraph or None
        """
        # To keep consistency with what the user expects, we make sure to evaluate on the remaining
        # inputset values if any before giving a copy of the OPGraph we trace
        self._eval_on_current_inputset()
        return deepcopy(self._op_graph)

    @property
    def compilation_configuration(self) -> Optional[CompilationConfiguration]:
        """Get a copy of the compilation configuration.

        Returns:
            Optional[CompilationConfiguration]: copy of the current compilation configuration.
        """
        return deepcopy(self._compilation_configuration)

    def __call__(self, *args: Any) -> Any:
        """Evaluate the OPGraph corresponding to the function being compiled and return result.

        Returns:
            Any: the result of the OPGraph evaluation.
        """
        self._current_inputset.append(deepcopy(args))

        inferred_args = {
            param_name: get_base_value_for_numpy_or_python_constant_data(val)(
                is_encrypted=is_encrypted
            )
            for (param_name, is_encrypted), val in zip(
                self._function_parameters_encrypted_status.items(), args
            )
        }

        if len(self._current_inputset) >= self.INPUTSET_SIZE_BEFORE_AUTO_BOUND_UPDATE:
            self._eval_on_current_inputset()

        self._trace_op_graph_if_needed(inferred_args)

        # For mypy
        assert self._op_graph is not None
        return self._op_graph(*args)

    def eval_on_inputset(self, inputset: Iterable[Union[Any, Tuple]]) -> None:
        """Evaluate the underlying function on an inputset in one go, populates OPGraph and bounds.

        Args:
            inputset (Iterable[Union[Any, Tuple]]): The inputset on which the function should be
                evaluated.
        """
        inputset_as_list = list(inputset)
        if len(inputset_as_list) == 0:
            return

        inferred_args = {
            param_name: get_base_value_for_numpy_or_python_constant_data(val)(
                is_encrypted=is_encrypted
            )
            for (param_name, is_encrypted), val in zip(
                self._function_parameters_encrypted_status.items(), self._current_inputset[0]
            )
        }

        self._trace_op_graph_if_needed(inferred_args)

        # For mypy
        assert self._op_graph is not None

        self._patch_op_graph_input_to_accept_any_integer_input()

        self._nodes_and_bounds = measure_op_graph_bounds_and_update(
            self._op_graph,
            inferred_args,
            inputset_as_list,
            self._compilation_configuration,
            self.compilation_artifacts,
            self._nodes_and_bounds,
            False,
        )

    def _eval_on_current_inputset(self) -> None:
        """Evaluate OPGraph on _current_inputset."""
        self.eval_on_inputset(self._current_inputset)
        self._current_inputset.clear()

    def _needs_tracing(self) -> bool:
        """Return whether we need to trace the function and populate the OPGraph."""
        return self._op_graph is None

    def _trace_op_graph_if_needed(self, inferred_args: Dict[str, BaseValue]) -> None:
        """Populate _op_graph with the OPGraph for _function_to_compile."""
        if not self._needs_tracing():
            return

        self._op_graph = compile_numpy_function_into_op_graph(
            self.function_to_compile,
            inferred_args,
            self._compilation_configuration,
            self.compilation_artifacts,
        )

    def _patch_op_graph_input_to_accept_any_integer_input(self) -> None:
        """Patch inputs as we don't know what data we expect."""

        # Can only do that if the OPGraph was created hence the test.
        if self._needs_tracing():
            return

        # For mypy
        assert self._op_graph is not None

        # Cheat on Input nodes to avoid issues during inputset eval as we do not know in advance
        # what the final bit width for the inputs should be
        for node in self._op_graph.input_nodes.values():
            for input_ in node.inputs:
                if isinstance(dtype := (input_.dtype), Integer):
                    dtype.bit_width = 128
                    dtype.is_signed = True
