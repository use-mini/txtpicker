{
  description = "Shortcut-driven floating snippet menu that pastes into the focused window (Hyprland + GNOME)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      version = "1.0";
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in
    {
      packages = forAll (pkgs:
        let
          # jeepney for the XDG portals, pygobject3 for the window.
          python = pkgs.python3.withPackages (ps: with ps; [ jeepney pygobject3 ]);

          cli = pkgs.stdenvNoCC.mkDerivation {
            pname = "txtpicker";
            inherit version;
            src = ./src/txtpicker.py;
            dontUnpack = true;

            # wrapGAppsHook4 is what makes the GTK typelibs findable; it also
            # carries the two prefixes below.
            nativeBuildInputs = [ pkgs.wrapGAppsHook4 pkgs.gobject-introspection ];
            buildInputs = [ pkgs.gtk4 pkgs.gtk4-layer-shell ];

            buildPhase = ''
              runHook preBuild
              cp $src txtpicker.py
              ${python}/bin/python3 -m py_compile txtpicker.py  # fail the build, not the shortcut
              # The script keeps `#!/usr/bin/env python3` so it runs from a
              # checkout; here it gets the interpreter pinned above.
              substituteInPlace txtpicker.py \
                --replace-fail '#!/usr/bin/env python3' '#!${python}/bin/python3'
              runHook postBuild
            '';

            installPhase = ''
              runHook preInstall
              install -Dm755 txtpicker.py $out/bin/txtpicker
              runHook postInstall
            '';

            # gtk4-layer-shell has to be loaded before GTK, hence LD_PRELOAD.
            # $out/bin on PATH is how the daemon finds itself: it starts
            # `txtpicker menu` as a child, and that child has to go through this
            # wrapper to get the GTK environment — argv[0] and __file__ both
            # point at the unwrapped script inside it.
            preFixup = ''
              gappsWrapperArgs+=(
                --prefix LD_PRELOAD : "${pkgs.gtk4-layer-shell}/lib/libgtk4-layer-shell.so"
                --prefix PATH : "$out/bin:${pkgs.lib.makeBinPath (with pkgs; [
                  wl-clipboard # clipboard on Wayland
                  xclip        # clipboard on X11
                  wtype        # pasting into Wayland windows
                  xdotool      # pasting into XWayland windows, which ignore wtype
                  libnotify    # notify-send
                ])}"
              )
            '';

            meta.mainProgram = "txtpicker";
          };

          # Launcher entry, so the app shows up in GNOME search, fuzzel, wofi, ...
          desktopItem = pkgs.makeDesktopItem {
            name = "io.github.TxtPicker";
            desktopName = "txtpicker";
            comment = "Pick a text snippet and copy it to the clipboard";
            exec = "${cli}/bin/txtpicker";
            icon = "edit-paste";
            categories = [ "Utility" ];
          };

          app = pkgs.symlinkJoin {
            name = "txtpicker";
            paths = [ cli desktopItem ];
          };
        in
        {
          txtpicker = app;
          default = app;
        });

      apps = forAll (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.txtpicker}/bin/txtpicker";
        };
      });

      # Everything needed to run ./src/txtpicker.py straight from the checkout.
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [ jeepney pygobject3 pytest ]))
            pkgs.gtk4
            pkgs.gtk4-layer-shell
            pkgs.gobject-introspection
          ];
          # Preloading the layer-shell library is per-program, so it is only
          # offered here as a variable:
          #   LD_PRELOAD=$GTK4_LAYER_SHELL ./src/txtpicker.py menu
          shellHook = ''
            export GTK4_LAYER_SHELL=${pkgs.gtk4-layer-shell}/lib/libgtk4-layer-shell.so
          '';
        };
      });

      checks = forAll (pkgs:
        let
          testPython = pkgs.python3.withPackages (ps: with ps; [ pytest pygobject3 jeepney ]);
        in
        {
          inherit (self.packages.${pkgs.stdenv.hostPlatform.system}) txtpicker;

          # Config, snippets, clipboard argv, child environment, filtering, key
          # parsing. The GTK typelibs are here because the key tests need Gdk,
          # not because a window is opened.
          tests = pkgs.runCommand "txtpicker-tests"
            {
              nativeBuildInputs = [ pkgs.gobject-introspection ];
              buildInputs = [ pkgs.gtk4 pkgs.gtk4-layer-shell ];
            } ''
            cp -r ${./src} src
            cp -r ${./tests} tests
            export HOME=$TMPDIR PYTHONDONTWRITEBYTECODE=1
            ${testPython}/bin/pytest -q tests
            touch $out
          '';
        });
    };
}
