{
  description = "Dev env for gpt-researcher (Nix + uv + npm)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python311
            uv
            nodejs_22
            git
            just
          ];

          shellHook = ''
            export NEXT_TELEMETRY_DISABLED=1
            echo "[gpt-researcher] Nix dev shell ready"
            echo "- Python: $(python --version 2>/dev/null)"
            echo "- Node: $(node --version 2>/dev/null)"
            echo "- uv: $(uv --version 2>/dev/null)"
            echo "Tip: load env vars with 'set -a; source .env; set +a' if needed."
            echo "Backend: make backend-dev"
            echo "Frontend: make frontend-dev"
          '';
        };
      });
}
