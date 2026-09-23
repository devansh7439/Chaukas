import QtQuick
import Chaukas

// Risk over time as thin bars (the reference's Steps card). The newest bar is copper.
Card {
    id: root
    readonly property var bars: dashboard.history.bars || []

    elevation: 1

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        spacing: 4
        AppText {
            text: dashboard.labels.risk_over_time
            color: Theme.inkMuted
            font.pixelSize: Theme.body
            wrapMode: Text.NoWrap
        }
        Row {
            spacing: 2
            AppText {
                id: now
                text: dashboard.view.scorePercent
                font.pixelSize: 30
                font.weight: Font.DemiBold
                wrapMode: Text.NoWrap
            }
            AppText {
                text: "%"
                font.pixelSize: Theme.bodyLarge
                font.weight: Font.DemiBold
                anchors.baseline: now.baseline
                wrapMode: Text.NoWrap
            }
        }
        AppText {
            text: dashboard.labels.peak + " " + (dashboard.history.peakPercent || 0) + "%"
            color: Theme.inkMuted
            font.pixelSize: Theme.label
            wrapMode: Text.NoWrap
        }
    }

    Row {
        id: chart
        anchors.right: parent.right
        anchors.rightMargin: 26
        anchors.top: parent.top
        anchors.topMargin: 26
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 26
        spacing: Math.max(4, Math.min(10, (root.width * 0.55 - root.bars.length * 5) / Math.max(1, root.bars.length)))
        Accessible.role: Accessible.Chart
        Accessible.name: dashboard.labels.risk_over_time + ", " + dashboard.labels.peak + " "
                         + (dashboard.history.peakPercent || 0) + "%"

        Repeater {
            model: root.bars
            Rectangle {
                required property real modelData
                required property int index
                readonly property bool newest: index === root.bars.length - 1
                width: 5
                height: chart.height
                radius: 2.5
                color: Theme.trackSoft
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    radius: parent.radius
                    height: Math.max(0, parent.height * parent.modelData)
                    color: parent.newest ? Theme.accent : Theme.ink
                    Behavior on height { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }
                }
            }
        }
    }
}
