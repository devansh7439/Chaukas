import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Chaukas

// Level "notice": a small card in the corner. Informs without interrupting.
Window {
    id: root
    objectName: "noticeWindow"
    property var main
    readonly property var view: dashboard.view
    readonly property bool shown: view.alertVisible && view.level === "notice"

    visible: shown
    width: 420
    height: body.implicitHeight + 64
    x: Screen.desktopAvailableWidth - width - 24
    y: Screen.desktopAvailableHeight - height - 24
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
    color: "transparent"
    title: "Chaukas"
    onVisibleChanged: if (visible) dashboard.protectWindow(root)

    Card {
        anchors.fill: parent
        anchors.margins: 16
        elevation: 2
        radius: Theme.radiusCard

        ColumnLayout {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 24
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                LevelChip { level: root.view.level; title: root.view.levelTitle }
                Item { Layout.fillWidth: true }
                AppText { text: "Chaukas"; color: Theme.inkMuted; font.pixelSize: Theme.label; font.weight: Font.DemiBold }
            }
            AppText {
                Layout.fillWidth: true
                text: root.view.objective
                font.pixelSize: Theme.bodyLarge + 1
                font.weight: Font.DemiBold
            }
            ReasonList {
                Layout.fillWidth: true
                reasons: root.view.reasons
                limit: 2
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                PillButton {
                    variant: "primary"
                    iconName: "lightbulb"
                    text: dashboard.labels.why_btn
                    onClicked: root.main.openWhy()
                }
                PillButton { text: dashboard.labels.dismiss; onClicked: dashboard.dismiss() }
            }
        }
    }
}
