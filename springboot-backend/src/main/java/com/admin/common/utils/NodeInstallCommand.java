package com.admin.common.utils;

/** Shared, shell-safe command generation for the node installation API. */
public final class NodeInstallCommand {
    private NodeInstallCommand() {}

    public static String build(String repo, String tag, String address, String secret) {
        if (repo == null || !repo.matches("[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
                || tag == null || !tag.matches("[A-Za-z0-9][A-Za-z0-9._-]*")
                || address == null || address.isBlank() || secret == null || secret.isBlank()) {
            throw new IllegalArgumentException("Invalid node installation configuration");
        }
        String url = "https://github.com/" + repo + "/releases/download/" + tag + "/install.sh";
        return "curl -fsSL " + url + " -o ./install.sh && chmod +x ./install.sh && "
                + "FLUX_REPO=" + quote(repo) + " FLUX_RELEASE_TAG=" + quote(tag)
                + " ./install.sh -a " + quote(address) + " -s " + quote(secret);
    }

    private static String quote(String value) {
        return "'" + value.replace("'", "'\"'\"'") + "'";
    }
}
