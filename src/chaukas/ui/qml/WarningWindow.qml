import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import Chaukas

// Level "warning": a side panel with the evidence and safe next steps.
Window {
    id: root
    objectName: "warningWindow"
    property var main
    readonly property var view: dashboard.view
    readonly property bool shown: view.alertVisible && view.level === "warning"

    visible: shown
    width: 470
    height: Math.min(Screen.desktopAvailableHeight - 32, 900)
    x: Screen.desktopAvailableWidth - width - 16
    y: 16
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    title: "Chaukas"
    onVisibleChanged: if (visible) dashboard.protectWindow(root)

    Card {
        anchors.fill: parent
        anchors.margins: 14
        elevation: 2
        color: Theme.panelTop
        colorBottom: Theme.panelBottom
        radius: Theme.radiusShell - 8

        ScrollView {
            id: scroll
            anchors.fill: parent
            anchors.margins: 6
            clip: true
            contentWidth: availableWidth
            contentHeight: column.implicitHeight + 44

            ColumnLayout {
                id: column
                x: 22
                y: 22
                width: scroll.availableWidth - 44
                spacing: 18

                RowLayout {
                    Layout.fillWidth: true
                    LevelChip { level: root.view.level; title: root.view.levelTitle }
                    Item { Layout.fillWidth: true }
                    AppText { text: root.view.callTime; color: Theme.inkMuted; font.pixelSize: Theme.label }
                }
                AppText {
                    Layout.fillWidth: true
                    text: root.view.headline
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                    font.letterSpacing: -0.3
                }
                AppText {
                    Layout.fillWidth: true
                    text: root.view.objective
                    font.pixelSize: Theme.bodyLarge + 1
                    font.weight: Font.Medium
                }
                AppText {
                    text: dashboard.labels.why_title
                    color: Theme.inkMuted
                    font.pixelSize: Theme.label
                    font.weight: Font.DemiBold
                }
                ReasonList { Layout.fillWidth: true; reasons: root.view.reasons; limit: 5 }
                DecisionPanel { Layout.fillWidth: true }
                Flow {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 12
                    spacing: 10
                    PillButton {
                        text: dashboard.labels.open_chaukas
                        iconName: "lightbulb"
                        onClicked: root.main.openWhy()
                    }
                    PillButton {
                        variant: "primary"
                        iconName: "check"
                        text: dashboard.labels.understand
                        onClicked: dashboard.dismiss()
                    }
                }
            }
        }
    }
}
