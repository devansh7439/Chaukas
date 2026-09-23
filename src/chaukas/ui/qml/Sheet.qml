import QtQuick
import QtQuick.Layouts
import Chaukas

// A centred card over a dimmed page: confirmations and quick info. Esc or the scrim closes.
Item {
    id: root
    property string kind: ""        // "end", "contact", "helpline" or ""
    readonly property bool shown: kind.length > 0

    anchors.fill: parent
    visible: opacity > 0
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Theme.fast } }
    focus: shown
    Keys.onEscapePressed: root.kind = ""

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusShell
        color: Qt.rgba(0.08, 0.08, 0.08, 0.45)
        TapHandler { onTapped: root.kind = "" }
    }

    Card {
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 80)
        height: body.implicitHeight + 64
        elevation: 2
        scale: root.shown ? 1 : 0.96
        Behavior on scale { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }

        ColumnLayout {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.margins: 32
            spacing: 16

            // End session: confirm, because it discards what Chaukas heard
            AppText {
                visible: root.kind === "end"
                Layout.fillWidth: true
                text: dashboard.labels.action_end + "?"
                font.pixelSize: Theme.title
                font.weight: Font.DemiBold
            }
            AppText {
                visible: root.kind === "end"
                Layout.fillWidth: true
                text: dashboard.labels.privacy_note
                color: Theme.inkMuted
                font.pixelSize: Theme.body
                lineHeight: 1.2
            }
            RowLayout {
                visible: root.kind === "end"
                Layout.fillWidth: true
                spacing: 12
                Item { Layout.fillWidth: true }
                PillButton { text: dashboard.labels.dismiss; onClicked: root.kind = "" }
                PillButton {
                    variant: "danger"
                    iconName: "trash-2"
                    text: dashboard.labels.action_end
                    onClicked: { dashboard.endSession(); root.kind = "" }
                }
            }

            // Trusted contact / helpline
            DecisionPanel {
                visible: root.kind === "contact" || root.kind === "helpline"
                Layout.fillWidth: true
                open: root.kind === "end" ? "" : root.kind
            }
            PillButton {
                visible: root.kind === "contact" || root.kind === "helpline"
                Layout.alignment: Qt.AlignRight
                text: dashboard.labels.dismiss
                onClicked: root.kind = ""
            }
        }
    }
}
