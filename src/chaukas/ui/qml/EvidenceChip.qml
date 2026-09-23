import QtQuick
import Chaukas

// One detected tactic and its current strength.
Card {
    id: root
    property string label: ""
    property int percent: 0

    implicitWidth: 158
    implicitHeight: 70
    radius: Theme.radiusInner
    elevation: 0.8
    Accessible.role: Accessible.StaticText
    Accessible.name: label + " " + percent + "%"

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        AppText {
            text: root.label
            color: Theme.inkMuted
            font.pixelSize: Theme.label
            wrapMode: Text.NoWrap
        }
        AppText {
            text: root.percent + "%"
            font.pixelSize: Theme.bodyLarge
            font.weight: Font.Bold
            wrapMode: Text.NoWrap
        }
    }

    Ring {
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        value: root.percent / 100
    }
}
