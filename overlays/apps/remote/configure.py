from pathlib import Path

def configure(root=Path("/")):
    sources=root/"etc/apt/sources.list.d"
    managed=sources/"reimuks-apps.list"
    generated=sources/"vscode.sources"
    if managed.is_file() and generated.is_file():
        text=generated.read_text()
        uri="https://packages.microsoft.com/repos/code"
        fields=dict(line.split(":",1) for line in text.splitlines()
                    if line and not line.startswith("#") and ":" in line)
        # Only remove the known single-source vendor-generated duplicate.
        # User-authored source files and other repositories remain intact.
        if ("### THIS FILE IS AUTOMATICALLY CONFIGURED ###" in text
                and fields.get("URIs", "").strip().rstrip("/")==uri
                and sum(line.startswith("URIs:") for line in text.splitlines())==1
                and any(line.startswith("deb ") and uri+" " in line
                        for line in managed.read_text().splitlines())):
            generated.unlink()
    entry=root/"usr/share/applications/google-chrome.desktop"
    if entry.is_file():
        text=entry.read_text()
        for binary in ("/usr/bin/google-chrome-stable","/usr/bin/google-chrome"):
            text=text.replace("Exec="+binary,"Exec=/usr/bin/reimuks-chrome")
        target=root/"usr/local/share/applications/google-chrome.desktop"
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text)

if __name__=="__main__":
    configure()
