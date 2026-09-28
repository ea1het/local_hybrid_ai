# Design Principles

## 1. Transparency

Wrappers must not change the observable behavior of the underlying tools. Command-line arguments, environment variables, exit codes, and stdout/stderr output should remain identical to what the original tool produces. A user or script calling a wrapped tool should not need to know a wrapper exists.

## 2. Safety

All user-supplied inputs must be validated before being passed to the underlying tool. No `eval()` or unbounded `exec()` calls with user data. Wrappers enforce argument validation, path sanitization, and environment isolation where appropriate.

**No `__pycache__` generation.** Python wrappers must never produce local `__pycache__` directories. This is achieved by executing wrapper code through `exec(compile(source, "<wrapper>", "exec"))` rather than importing or running modules directly. The `__pycache__` folder stays clean — wrappers are self-contained scripts, not importable packages.

## 3. Graceful Degradation

Some tools in `tools/` exist only as compiled `.pyc` files with no accessible source code. Wrappers for these must detect the absence of source, report a clear and actionable message, and offer a recovery path (e.g., a stub or instructions to restore the original). The wrapper must never crash silently or produce cryptic errors.

## 4. Zero Dependencies

Wrappers must work with only what ships with a standard Python installation and a POSIX-compatible shell. No third-party packages, no virtual environments required for the wrapper layer itself. This ensures portability across development machines and CI pipelines.

## 5. Single Entry Point

A single CLI command (`tool <name>`) serves as the universal entry point. It discovers the requested tool, validates it exists, and delegates to the appropriate wrapper (shell or Python). Users interact with one interface regardless of what language a tool is written in.

---

## Additional Principles

### Complete Documentation

Every wrapper must be fully documented with Markdown files in the `docs/` directory. Each tool gets a representative documentation file covering:

- Purpose and description
- Usage examples (command-line invocations)
- Arguments and flags
- Exit codes
- Known limitations

Documentation is not an afterthought — it is part of the deliverable.

### Command-Line Help

Every wrapper must provide built-in inline help accessible via `--help` or `-h`. This includes:

- A brief description of what the tool does
- Available arguments and flags with descriptions
- Usage examples
- Exit code documentation

Users should never need to read source code to understand how to invoke a tool.

### Stack Independence

Existing stacks must continue to function independently, exactly as they do today — each runnable one at a time without requiring the wrapper. Auxiliary files placed in the `stack/` directory (if any are added to support wrapper functionality) are only meaningful when accessed through the wrapper. These files have no standalone purpose and should not be invoked directly.

The wrapper layer is an enhancement, not a replacement. Existing workflows that call tools directly must continue to work unchanged.

### Selective Testing

A `tests/` directory exists at the project root, but tests are created only for code that meaningfully benefits from automated verification. No tests for the sake of having tests.

Guidelines:

- Prioritize quality over quantity. Ten well-designed, meaningful tests are preferred over four hundred superficial ones.
- Test wrapper logic that validates input, handles errors, and manages delegation.
- Do not test underlying tools — they have their own coverage (if any).
- Skip tests for trivial wrappers that simply pass through arguments.

The bar is: "Does this test catch a real bug or verify a real contract?" If the answer is no, skip it.
