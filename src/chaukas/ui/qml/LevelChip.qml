import QtQuick
import Chaukas

// The alert level as icon + word + colour, never colour alone.
Rectangle {
    id: root
    property string level: "quiet"
    property string title: ""
    property bool darkSurface: false

    readonly property color tone: Theme.levelColor(level)

    implicitWidth: row.implicitWidth + 24
    implicitHeight: 32
    radius: height / 2
    color: darkSurface ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(tone.r, tone.g, tone.b, 0.12)
    Accessible.role: Accessible.StaticText
    Accessible.name: title

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Icon {
            name: Theme.levelIcon(root.level)
            tint: root.darkSurface ? Theme.textOnDark : root.tone
            size: 16
            anchors.verticalCenter: parent.verticalCenter
        }
        AppText {
            text: root.title
            color: root.darkSurface ? Theme.textOnDark : root.tone
            font.pixelSize: Theme.label
            font.weight: Font.Bold
            wrapMode: Text.NoWrap
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
