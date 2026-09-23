import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Chaukas

// The Chaukas window: a soft rounded panel on a grey backdrop, a dark pill sidebar, and
// four pages. Alert windows are declared here too, so they can open the Why page.
Window {
    id: main
    objectName: "mainWindow"

    property bool headless: false
    property int requestedWidth: 0
    property int requestedHeight: 0
    property int page: 0

    function openWhy() {
        page = 1
        if (!headless) {
            main.show()
            main.raise()
            main.requestActivate()
        }
    }

    width: requestedWidth > 0 ? requestedWidth : Math.min(1440, Screen.desktopAvailableWidth - 48)
    height: requestedHeight > 0 ? requestedHeight : Math.min(930, Screen.desktopAvailableHeight - 48)
    minimumWidth: 1120
    minimumHeight: 780
    visible: true
    title: "Chaukas"
    color: Theme.backdrop

    Shortcut { sequence: "Ctrl+1"; onActivated: main.page = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: main.page = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: main.page = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: main.page = 3 }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.backdrop }
            GradientStop { position: 1.0; color: Theme.backdropDeep }
        }
    }

    Item {
        id: shell
        anchors.fill: parent
        anchors.margins: 18

        SoftShadow { radius: Theme.radiusShell; strength: 0.14; offsetY: 10; spread: 3 }
        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusShell
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.8)
            gradient: Gradient {
                GradientStop { position: 0.0; color: Theme.panelTop }
                GradientStop { position: 1.0; color: Theme.panelBottom }
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 30

            Sidebar {
                Layout.fillHeight: true
                Layout.preferredWidth: 116
                current: main.page
                onNavigate: (index) => main.page = index
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: 8
                Layout.bottomMargin: 4
                Layout.rightMargin: 6
                currentIndex: main.page

                HomePage {
                    onOpenWhy: main.page = 1
                    onOpenPrivacy: main.page = 2
                    onShowSheet: (kind) => sheet.kind = kind
                }
                WhyPage {}
                PrivacyPage { onEndSession: sheet.kind = "end" }
                SettingsPage {}
            }
        }

        Sheet { id: sheet }
        Toast { id: toast }
    }

    Connections {
        target: dashboard
        function onToast(message) { toast.show(message) }
    }

    NoticeWindow { main: main }
    WarningWindow { main: main }
    CriticalWindow {
        main: main
        headless: main.headless
        fixedWidth: main.headless ? main.width : 0
        fixedHeight: main.headless ? main.height : 0
    }
}
