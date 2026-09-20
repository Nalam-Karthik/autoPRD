"""AST-based source code parser for structural context extraction.

Parses Python source code using the built-in `ast` module and extracts
structural information such as imports, class definitions, function
definitions, and their hierarchical relationships.
"""

from __future__ import annotations

import ast
import keyword
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ImportInfo:
    """Information about a Python import statement."""

    module: str
    alias: Optional[str] = None
    line: int = 0
    is_stdlib: bool = False
    is_third_party: bool = False
    is_local: bool = False


@dataclass
class FunctionInfo:
    """Information about a Python function."""

    name: str
    line: int
    col: int
    end_line: int
    end_col: int
    args: List[str] = field(default_factory=list)
    returns: Optional[str] = None
    is_async: bool = False
    is_method: bool = False
    class_name: Optional[str] = None


@dataclass
class MethodInfo(FunctionInfo):
    """Information about a Python method (function within a class)."""

    pass


@dataclass
class ClassInfo:
    """Information about a Python class."""

    name: str
    line: int
    col: int
    end_line: int
    end_col: int
    methods: List[MethodInfo] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)
    decorator_names: List[str] = field(default_factory=list)


@dataclass
class structural_context_context:
    """Root container for all extracted structural context."""

    filename: str
    imports: List[ImportInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    raw_source: str = ""


@dataclass
class ASTExtractionResult:
    """Result of AST-based source code extraction."""

    structural_context: structural_context_context
    success: bool = True
    error_message: Optional[str] = None


class ASTParser:
    """AST-based parser for extracting structural context from Python source code."""

    def __init__(self):
        self._stdlib_modules: Optional[Set[str]] = None

    @property
    def stdlib_modules(self) -> Set[str]:
        """Lazy-loaded set of stdlib module names."""
        if self._stdlib_modules is None:
            self._stdlib_modules = self._load_stdlib_modules()
        return self._stdlib_modules

    @staticmethod
    def _load_stdlib_modules() -> Set[str]:
        """Load a set of standard library module names.

        In a real deployment, this could read from sys.stdlinfo or a
        curated list. For now, we include common ones.
        """
        return {
            "abc",
            "argparse",
            "array",
            "base64",
            "binascii",
            "binascii",
            "calendar",
            "collections",
            "configparser",
            "copy",
            "csv",
            "datetime",
            "decimal",
            "email",
            "encodings",
            "enum",
            "fileinput",
            "functools",
            "genericpath",
            "glob",
            "html",
            "http",
            "importlib",
            "io",
            "json",
            "math",
            "multiprocessing",
            "operator",
            "os",
            "pathlib",
            "pickle",
            "pkgutil",
            "platform",
            "pprint",
            "profile",
            "pydoc",
            "random",
            "re",
            "secrets",
            "select",
            "shutil",
            "signal",
            "socket",
            "sqlite3",
            "string",
            "stringprep",
            "struct",
            "subprocess",
            "sys",
            "tempfile",
            "threading",
            "time",
            "token",
            "traceback",
            "typing",
            "unittest",
            "urllib",
            "uuid",
            "warnings",
            "weakref",
            "winsound",
            "xml",
        }

    def parse(self, source: str, filename: str = "<string>") -> ASTExtractionResult:
        """Parse Python source code and extract structural context.

        Args:
            source: Python source code as a string.
            filename: Name of the file being parsed (for error reporting).

        Returns:
            ASTExtractionResult containing the extracted structural context.
        """
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as e:
            return ASTExtractionResult(
                structural_context=structural_context_context(
                    filename=filename, raw_source=source
                ),
                success=False,
                error_message=f"Syntax error: {e}",
            )

        context = structural_context_context(
            filename=filename, raw_source=source
        )

        # Extract imports at module level
        context.imports = self._extract_imports(tree, filename)

        # Extract top-level classes and functions (not nested inside other constructs)
        # Use iter_child_nodes instead of walk to avoid picking up methods inside classes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_info = self._extract_class(node)
                context.classes.append(class_info)
            elif isinstance(node, ast.FunctionDef):
                func_info = self._extract_function(node)
                context.functions.append(func_info)

        return ASTExtractionResult(structural_context=context, success=True)

    def _extract_imports(self, tree: ast.AST, filename: str) -> List[ImportInfo]:
        """Extract import information from the AST.

        Handles: import X, from X import Y, import X as Z, from X import Y as Z
        """
        imports: List[ImportInfo] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    alias_name = alias.asname
                    info = ImportInfo(
                        module=module,
                        alias=alias_name,
                        line=node.lineno,
                    )
                    # Classify the import type
                    if module.split(".")[0] in self.stdlib_modules:
                        info.is_stdlib = True
                    elif "." in module:
                        # Likely local package import
                        info.is_local = True
                    else:
                        info.is_third_party = True
                    imports.append(info)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    alias_name = alias.asname
                    # Use just the module name, not concatenated with imported name
                    imported_module = module if module else alias.name
                    info = ImportInfo(
                        module=imported_module,
                        alias=alias_name,
                        line=node.lineno,
                    )
                    # Classify the import type
                    if module and module.split(".")[0] in self.stdlib_modules:
                        info.is_stdlib = True
                    elif module:
                        info.is_local = True
                    else:
                        # Relative import or no module context
                        info.is_local = True
                    imports.append(info)

        return imports

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        """Extract class definition information including methods and bases."""
        methods: List[MethodInfo] = []

        # Extract methods defined directly in this class (not inherited)
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                # Skip dunder methods for cleaner output, or include them all
                is_dunder = item.name.startswith("__") and item.name.endswith("__")
                if not is_dunder:
                    meth_info = self._extract_method(item, node.name)
                    methods.append(meth_info)

        # Extract base class names
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(self._get_attr_path(base))

        decorator_names = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorator_names.append(dec.id)
            elif isinstance(dec, ast.Constant):
                decorator_names.append(str(dec.value))

        return ClassInfo(
            name=node.name,
            line=node.lineno,
            col=node.col_offset,
            end_line=node.end_lineno,
            end_col=node.end_col_offset,
            methods=methods,
            bases=bases,
            decorator_names=decorator_names,
        )

    def _extract_method(self, node: ast.FunctionDef, class_name: str) -> MethodInfo:
        """Extract method information from a function definition within a class."""
        args: List[str] = []

        # Extract argument names (skip 'self')
        if node.args.args:
            # Skip 'self' or 'cls' as the first arg
            for arg in node.args.args:
                if arg.arg not in ("self", "cls"):
                    args.append(arg.arg)

        returns = None
        if node.returns:
            if isinstance(node.returns, ast.Constant):
                returns = str(node.returns.value)
            elif isinstance(node.returns, ast.Name):
                returns = node.returns.id

        is_async = isinstance(node, ast.AsyncFunctionDef)  # type: ignore

        return MethodInfo(
            name=node.name,
            line=node.lineno,
            col=node.col_offset,
            end_line=node.end_lineno,
            end_col=node.end_col_offset,
            args=args,
            returns=returns,
            is_async=is_async,
            is_method=True,
            class_name=class_name,
        )

    def _extract_function(self, node: ast.FunctionDef) -> FunctionInfo:
        """Extract function information from the AST."""
        args: List[str] = []

        for arg in node.args.args:
            if arg.arg not in ("self", "cls"):
                args.append(arg.arg)

        returns = None
        if node.returns:
            if isinstance(node.returns, ast.Constant):
                returns = str(node.returns.value)
            elif isinstance(node.returns, ast.Name):
                returns = node.returns.id

        is_async = isinstance(node, ast.AsyncFunctionDef)  # type: ignore

        return FunctionInfo(
            name=node.name,
            line=node.lineno,
            col=node.col_offset,
            end_line=node.end_lineno,
            end_col=node.end_col_offset,
            args=args,
            returns=returns,
            is_async=is_async,
            is_method=False,
        )

    @staticmethod
    def _get_attr_path(node: ast.Attribute) -> str:
        """Get the attribute path from an AST Attribute node."""
        parts: List[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)


def extract_structural_context(
    source: str, filename: str = "<string>"
) -> ASTExtractionResult:
    """Convenience function to extract structural context from Python source.

    Args:
        source: Python source code as a string.
        filename: Name of the file being parsed.

    Returns:
        ASTExtractionResult with the extracted structural context.
    """
    parser = ASTParser()
    return parser.parse(source, filename)


if __name__ == "__main__":
    # Simple demo
    sample_code = '''"""Sample module for demonstration."""

import os
import json
from datetime import datetime

# Third-party
import numpy as np

class User:
    """User model."""

    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email

    def get_name(self) -> str:
        """Return the user's name."""
        return self.name

    def greet(self) -> str:
        return f"Hello, {self.name}!"


def calculate_total(items: List[float]) -> float:
    """Calculate the total of a list of numbers."""
    return sum(items)


class MathUtils:
    """Utility functions for math operations."""

    PI = 3.14159

    def add(self, a: float, b: float) -> float:
        return a + b

    def multiply(self, a: float, b: float) -> float:
        return a * b
'''

    result = extract_structural_context(sample_code, "sample.py")
    if result.success:
        ctx = result.structural_context
        print(f"Filename: {ctx.filename}")
        print(f"\nImports ({len(ctx.imports)}):")
        for imp in ctx.imports:
            tag = ""
            if imp.is_stdlib:
                tag = "[STDLIB]"
            elif imp.is_local:
                tag = "[LOCAL]"
            elif imp.is_third_party:
                tag = "[3RD-PTY]"
            print(f"  {tag} {imp.module}" + (f" as {imp.alias}" if imp.alias else ""))
        print(f"\nClasses ({len(ctx.classes)}):")
        for cls in ctx.classes:
            print(f"  {cls.name} (line {cls.line})")
            print(f"    Bases: {cls.bases}")
            print(f"    Methods: {[m.name for m in cls.methods]}")
            print(f"    Decorators: {cls.decorator_names}")
        print(f"\nFunctions ({len(ctx.functions)}):")
        for func in ctx.functions:
            print(f"  {func.name} (line {func.line})" + (f" async" if func.is_async else ""))
            if func.args:
                print(f"    Args: {func.args}")
            if func.returns:
                print(f"    Returns: {func.returns}")
    else:
        print(f"Error: {result.error_message}")