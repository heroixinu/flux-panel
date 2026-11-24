package com.admin;

import com.admin.common.utils.NodeInstallCommand;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class NodeInstallCommandTests {
    @Test
    void previewAndReleaseUseSameRepositoryAndTagForScriptAndBinary() {
        for (String tag : new String[]{"sqlite-default", "1.5.0"}) {
            String command = NodeInstallCommand.build("heroixinu/flux-panel", tag, "[2001:db8::1]:6365", "test-secret");
            assertEquals("curl -fsSL https://github.com/heroixinu/flux-panel/releases/download/" + tag
                    + "/install.sh -o ./install.sh && chmod +x ./install.sh && FLUX_REPO='heroixinu/flux-panel'"
                    + " FLUX_RELEASE_TAG='" + tag + "' ./install.sh -a '[2001:db8::1]:6365' -s 'test-secret'", command);
        }
    }

    @Test
    void rejectsUnsafeRepoOrTagAndQuotesShellMetacharacters() {
        assertThrows(IllegalArgumentException.class, () -> NodeInstallCommand.build("evil;command", "sqlite-default", "example:80", "secret"));
        assertThrows(IllegalArgumentException.class, () -> NodeInstallCommand.build("heroixinu/flux-panel", "../bad", "example:80", "secret"));
        assertThrows(IllegalArgumentException.class, () -> NodeInstallCommand.build("heroixinu/flux-panel", "sqlite-default", "", "secret"));
        assertTrue(NodeInstallCommand.build("heroixinu/flux-panel", "sqlite-default", "example:80", "a'b$(false)").endsWith(" -s 'a'\"'\"'b$(false)'"));
    }
}
