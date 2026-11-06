pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
QtObject {
    id: root
    property var catalog: ({icons: {}, aliases: {}})
    property string lastOutput: ""
    property Process scanner: Process {
        command: ["/usr/bin/python3", "-m", "serpantinum_icon_fix.catalog", "__THEME__"]
        environment: ({"PYTHONPATH": "__PACKAGE__"})
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    if (text !== root.lastOutput) {
                        root.catalog = JSON.parse(text);
                        root.lastOutput = text;
                    }
                } catch (e) { console.warn("Icon catalog: " + e); }
            }
        }
    }
    property Timer refresh: Timer {
        interval: 3600000; running: true; repeat: true
        onTriggered: if (!scanner.running) scanner.running = true
    }
    function candidates(value) {
        let result = [], names = [];
        function add(url) { if (url && result.indexOf(url) < 0) result.push(url); }
        function name(n) { if (n && names.indexOf(n) < 0) names.push(n); }
        function direct(v) {
            if (v.charAt(0) === "/") {
                add("file://" + v.split("/").map(encodeURIComponent).join("/"));
                return true;
            }
            if (/^(file|image|qrc|data|https?):/.test(v)) { add(v); return true; }
            return false;
        }
        let raw = String(value || "").trim();
        if (!raw) return result;
        direct(raw);
        name(raw);
        name(raw.replace(/\.(png|svgz?|xpm|ico|webp|jpe?g|desktop)$/i, ""));
        let alias = catalog.aliases[raw.toLowerCase()] || catalog.aliases[raw.replace(/\.desktop$/i, "").toLowerCase()];
        if (alias) { direct(alias); name(alias); }
        if (raw.indexOf("/") >= 0) name(raw.substring(raw.lastIndexOf("/")+1).replace(/\.[^.]+$/, ""));
        let initial = names.slice();
        for (let n of initial) name(n.toLowerCase());
        for (let n of names) {
            if (n.indexOf("/") < 0) add(Quickshell.iconPath(n, true));
            for (let url of (catalog.icons[n] || [])) add(url);
        }
        return result;
    }
}
