// SPDX-License-Identifier: MIT
#include <QQmlEngine>
#include <QQmlExtensionPlugin>
#include <KSvg/ImageSet>

// Keep decoded popup backgrounds in memory instead of repeatedly decoding the
// PNG shared cache on Plasma's GUI thread. Use the supported KSvg API; no
// private ABI interception or replacement of distribution libraries is needed.
class PopupCachePlugin final : public QQmlExtensionPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QQmlExtensionInterface_iid)
public:
    void registerTypes(const char *uri) override
    {
        qmlRegisterModule(uri, 1, 0);
    }

    void initializeEngine(QQmlEngine *engine, const char *) override
    {
        // KSvg 6.13's 16 MiB shared cache gives KImageCache only 2 MiB of
        // decoded pixmaps. A 128 MiB shared budget gives 16 MiB locally.
        // ImageSet shares the process-wide theme; retain it for our lifetime.
        auto *images = new KSvg::ImageSet(engine);
        images->setCacheLimit(128 * 1024);
    }
};

#include "popup-cache.moc"
