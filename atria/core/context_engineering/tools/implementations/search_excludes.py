"""Default directory/pattern excludes for codebase search.

Covers 20+ programming languages and ecosystems. Extracted from ``file_ops`` so
the exclude list can be maintained (and reused) independently of the file tools.
"""

from __future__ import annotations

# Covers 20+ programming languages and ecosystems
DEFAULT_SEARCH_EXCLUDES = [
    # ===== Package/Dependency Directories =====
    "node_modules",  # JavaScript/TypeScript (npm, yarn, pnpm, bun)
    "bower_components",  # Bower (legacy JS)
    "jspm_packages",  # JSPM
    "vendor",  # Go, PHP (Composer), Ruby (Bundler)
    "Pods",  # Swift/Objective-C (CocoaPods)
    ".bundle",  # Ruby Bundler
    "packages",  # Dart/Flutter, .NET
    ".pub-cache",  # Dart pub
    ".pub",  # Dart pub
    "deps",  # Elixir Mix
    ".nuget",  # .NET NuGet
    ".m2",  # Java Maven, Clojure
    # ===== Virtual Environments =====
    ".venv",  # Python (standard)
    "venv",  # Python (common)
    "env",  # Python (common)
    ".env",  # Python/Node env dirs
    "ENV",  # Python
    ".virtualenvs",  # virtualenvwrapper
    ".conda",  # Conda environments
    # ===== Build Output Directories =====
    "build",  # Universal (C/C++, Python, Gradle, etc.)
    "dist",  # Universal (JS, Python, Haskell)
    "out",  # TypeScript, Android, general
    "target",  # Rust (Cargo), Java (Maven), Scala (sbt), Clojure
    "bin",  # .NET, Go, general compiled output
    "obj",  # .NET intermediate
    "lib",  # Compiled libraries
    "_build",  # Elixir, Erlang
    "ebin",  # Erlang compiled
    "dist-newstyle",  # Haskell Cabal
    ".build",  # Swift Package Manager
    "DerivedData",  # Xcode
    "CMakeFiles",  # CMake build artifacts
    ".cmake",  # CMake cache
    # ===== Framework-Specific Build =====
    ".next",  # Next.js
    ".nuxt",  # Nuxt.js
    ".angular",  # Angular CLI
    ".svelte-kit",  # SvelteKit
    ".vuepress",  # VuePress
    ".gatsby-cache",  # Gatsby
    ".parcel-cache",  # Parcel bundler
    ".turbo",  # Turborepo
    "dist_electron",  # Electron
    # ===== Cache Directories =====
    ".cache",  # Universal cache
    "__pycache__",  # Python bytecode
    ".pytest_cache",  # Pytest
    ".mypy_cache",  # Mypy type checker
    ".ruff_cache",  # Ruff linter
    ".hypothesis",  # Hypothesis testing
    ".tox",  # Tox testing
    ".nox",  # Nox testing
    ".eslintcache",  # ESLint
    ".stylelintcache",  # Stylelint
    ".gradle",  # Gradle
    ".dart_tool",  # Dart
    ".mix",  # Elixir
    ".cpcache",  # Clojure
    ".lsp",  # Clojure LSP
    # ===== IDE/Editor Directories =====
    ".idea",  # JetBrains IDEs
    ".vscode",  # VS Code
    ".vscode-test",  # VS Code extension testing
    ".vs",  # Visual Studio
    ".metadata",  # Eclipse
    ".settings",  # Eclipse
    "xcuserdata",  # Xcode user data
    ".netbeans",  # NetBeans
    # ===== Version Control =====
    ".git",  # Git
    ".svn",  # Subversion
    ".hg",  # Mercurial
    # ===== Coverage/Testing Output =====
    "coverage",  # Universal coverage
    "htmlcov",  # Python coverage HTML
    ".nyc_output",  # NYC (Istanbul) coverage
    # ===== Language-Specific Metadata =====
    ".eggs",  # Python eggs
    ".Rproj.user",  # R Studio
    ".julia",  # Julia packages
    "_opam",  # OCaml
    ".cabal-sandbox",  # Haskell Cabal sandbox
    ".stack-work",  # Haskell Stack
    "blib",  # Perl build
    # ===== Generated/Minified Files (glob patterns) =====
    "*.min.js",  # Minified JavaScript
    "*.min.css",  # Minified CSS
    "*.bundle.js",  # Bundled JavaScript
    "*.chunk.js",  # Webpack chunks
    "*.map",  # Source maps
    "*.pyc",  # Python compiled
    "*.pyo",  # Python optimized
    "*.class",  # Java compiled
    "*.o",  # C/C++ object files
    "*.so",  # Shared libraries
    "*.dylib",  # macOS dynamic libraries
    "*.dll",  # Windows DLLs
    "*.exe",  # Windows executables
    "*.beam",  # Erlang/Elixir compiled
    "*.hi",  # Haskell interface
    "*.dyn_hi",  # Haskell dynamic interface
    "*.dyn_o",  # Haskell dynamic object
    "*.egg-info",  # Python egg info
]
