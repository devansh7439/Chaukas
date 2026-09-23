import QtQuick
import QtQuick.Layouts
import Chaukas

// "Risk right now": level, what the caller seems to want, and the risk bar.
// The reference's "You're 45% to your daily goal" card.
Card {
    id: root
    signal explain()

    readonly property var view: dashboard.view
    readonly property color tone: Theme.levelColor(view.level)

    color: Theme.surfaceTop
    colorBottom: Theme.surface
    elevation: 0.35
    radius: Theme.radiusCard + 4

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                RowLayout {
                    spacing: 10
                    AppText {
                        text: dashboard.labels.risk_now
                        color: Theme.inkMuted
                        font.pixelSize: Theme.label
                        font.weight: Font.Medium
                        wrapMode: Text.NoWrap
                    }
                    LevelChip { level: root.view.level; title: root.view.levelTitle }
                }
                AppText {
                    Layout.fillWidth: true
                    text: root.view.objective
                    font.pixelSize: Theme.heading
                    font.weight: Font.DemiBold
                    lineHeight: 1.1
                    maximumLineCount: 2
                }
            }

            CircleButton {
                Layout.alignment: Qt.AlignTop
                iconName: root.view.level === "quiet" ? "zap" : Theme.levelIcon(root.view.level)
                tone: root.view.level === "quiet" ? Theme.accent : root.tone
                label: dashboard.labels.why_btn
                onClicked: root.explain()
            }
        }

        // The risk bar: a white pill growing in a grey track, as in the reference.
        Rectangle {
            id: track
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            radius: height / 2
            color: Theme.track
            Accessible.role: Accessible.ProgressBar
            Accessible.name: dashboard.labels.risk + " " + root.view.scorePercent + "%"

            Rectangle {
                x: 4
                anchors.verticalCenter: parent.verticalCenter
                height: parent.height - 8
                radius: height / 2
                width: Math.max(height, (track.width - 8) * root.view.scorePercent / 100)
                color: Theme.raised
                Behavior on width { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }
                SoftShadow { radius: parent.radius; strength: 0.06; offsetY: 2; spread: 1.6 }
            }

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                AppText {
                    text: root.view.scorePercent
                    font.pixelSize: Theme.body
                    font.weight: Font.Bold
                    wrapMode: Text.NoWrap
                }
                AppText {
                    text: "/100"
                    color: Theme.inkMuted
                    font.pixelSize: Theme.body
                    wrapMode: Text.NoWrap
                }
            }
        }
    }
}
