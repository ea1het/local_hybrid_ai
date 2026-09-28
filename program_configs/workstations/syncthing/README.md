# Obsidian Second Brain with Syncthing

Sync one Obsidian vault between a macOS, iPhone, or iPad client user device and the local AI (container) server infrastructure so agents can read the same Markdown notes. This is a setup guide; the repository does not install Syncthing or grant agents access automatically. The server commands below assume Linux.

## macOS client user device

Install Syncthing with Homebrew, start it at login, and create a local vault directory:

```sh
brew install syncthing
brew services start syncthing
mkdir -p "$HOME/Documents/SecondBrain"
```

Open or create this directory as a vault in Obsidian. If the vault already exists elsewhere, use its existing path when configuring Syncthing instead of creating another copy.

After preparing the server host below, open Syncthing at `http://127.0.0.1:8384` on the Mac. Keep its web interface bound to localhost. To reach the server's web interface from the Mac, run `ssh -L 18384:127.0.0.1:8384 your-user@your-server-host` (replace the example user and host), then open `http://127.0.0.1:18384`.

Use **Actions → Show ID** on each host and **Add Remote Device** to pair them; confirm the device IDs on both sides. On the Mac, add the Obsidian vault as a **Send & Receive** folder with ID `second-brain`. Set **Folder Path** to the absolute path shown by `printf '%s\n' "$HOME/Documents/SecondBrain"`, or to the existing vault path. Share the folder with the server and complete the server steps below. Verify a test note syncs in both directions before relying on the server copy.

## iPhone or iPad client user device

Install **Obsidian** and [Möbius Sync](https://mobiussync.com/) from the App Store. Syncthing has no official iOS app; Möbius Sync is a third-party compatible client. In Obsidian, create a vault named `SecondBrain` stored **On My iPhone** or **On My iPad**, with **Store in iCloud** off. In the Files app, confirm the vault appears under **On My iPhone/iPad → Obsidian → SecondBrain**.

After preparing the server host below, get its device ID with **Actions → Show ID** on the server's local web interface, or through an SSH tunnel from a computer. In Möbius Sync, add that ID as a remote device; accept the iPhone or iPad's device ID on the server and confirm it matches. Pair each mobile device separately.

In Möbius Sync, add a **Send & Receive** folder using **Pick External Folder** and select the Obsidian vault. Give it the folder ID `second-brain`, share it with the server, and complete the server steps below. Do not select a folder inside Möbius Sync's own storage: Obsidian may not be able to open it as a vault. Möbius Sync cannot use an iCloud folder for this external-folder feature, and syncing another app's folder requires its paid unlock. Back up an existing vault before granting external-folder access.

Keep Möbius Sync open until the first transfer finishes. Verify a test note syncs in both directions. iOS limits background activity, so open the app and wait for it to sync before switching devices after an edit. See the [Möbius Sync FAQ](https://mobiussync.com/faq/) for current external-folder, purchase, and background-sync limits.

## Local AI server infrastructure

Install Syncthing from the host distribution's package repository, then start it as the user who will own the vault (do not run it as root). For Debian or Ubuntu:

```sh
sudo apt update
sudo apt install syncthing
systemctl --user enable --now syncthing.service
mkdir -p "$HOME/Documents/SecondBrain"
```

If the server host must continue syncing while that user is logged out, enable user lingering with `sudo loginctl enable-linger "$USER"`. Check that Syncthing is running with `systemctl --user status syncthing.service`. Keep the vault directory owned by its Syncthing user.

Open the server's Syncthing interface locally at `http://127.0.0.1:8384`, or use the SSH tunnel described in the macOS section. Keep the web interface bound to localhost. Pair each client by its device ID. For the first client, accept the `second-brain` folder invitation, set **Folder Path** to the server's absolute `$HOME/Documents/SecondBrain` path, and choose **Send & Receive**. The paths can differ between devices; the folder ID must match. For each additional client, share the existing server folder with that device and let its initial sync finish before adding another.

If the devices cannot connect, check that they can reach each other and that the host firewall permits Syncthing's configured sync and discovery ports. Do not expose the web interface on a public address to solve a connectivity problem.

## Agent access on the local AI server

Give each agent only the vault path it needs. For a containerized agent, bind mount the server host's vault read only, using the real absolute path for that host:

```yaml
services:
  agent:
    volumes:
      - /home/<user>/Documents/SecondBrain:/mnt/second-brain:ro
```

Use `/mnt/second-brain` as the agent's document root. Add this mount to an agent's existing Compose service only after identifying that service and its access requirements; the example above is not a complete deployment. A host-based agent can instead read the local directory with filesystem permissions limited to that directory. Do not give agents write access unless editing the vault is an explicit requirement. Syncthing replicates files; agent search or indexing must be configured separately.

## Verify and maintain

Confirm that each client's test note appears on the server host and that an edit on the server returns to its client. Verify that the intended agent can read the note through its mounted path. Remove the test notes after the round trips complete.

Syncthing also propagates deletions and conflicting edits. Keep an independent backup of the vault and avoid simultaneous edits to the same note on both hosts. Review the vault before sharing it with agents: only put material there that those agents may read. If the Obsidian UI state causes needless conflicts, add `.obsidian/workspace*` to the folder's ignore patterns on **both** devices; ignore patterns are local to each device.
