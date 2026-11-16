{
  description = "llvim: a log is a git-tracked sequence of tagged messages";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux"];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in {
      # The llvim commands, with tmux and git on their PATH.
      packages = forAll (pkgs: rec {
        llvim = pkgs.python312Packages.buildPythonApplication {
          pname = "llvim";
          version = "0.1.0";
          pyproject = true;
          src = pkgs.lib.fileset.toSource {
            root = ./.;
            fileset = pkgs.lib.fileset.unions [ ./pyproject.toml ./README.md ./src ./tests ];
          };
          build-system = [ pkgs.python312Packages.uv-build ];
          makeWrapperArgs = [ "--prefix" "PATH" ":" (pkgs.lib.makeBinPath [ pkgs.tmux pkgs.git ]) ];
          nativeCheckInputs = [ pkgs.python312Packages.pytestCheckHook pkgs.git pkgs.tmux ];
        };
        default = llvim;
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [ pkgs.uv pkgs.python312 pkgs.git pkgs.tmux ];
          env = {
            UV_PYTHON_DOWNLOADS = "never";
            UV_PYTHON = "${pkgs.python312}/bin/python";
          };
          # after `uv sync`, the commands are on PATH inside the shell
          shellHook = ''
            if [ -d "$PWD/.venv/bin" ]; then export PATH="$PWD/.venv/bin:$PATH"; fi
          '';
        };
      });
    };
}
