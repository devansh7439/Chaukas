import QtQuick
import Chaukas

// A short confirmation at the bottom of the window; hides itself after 3.5 s and never
// takes focus.
Item {
    id: root
    property string message: ""

    function show(text) {
        message = text
        timer.restart()
    }

    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 36
    width: pill.width
    height: 52
    opacity: timer.running ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: Theme.normal } }
    Accessible.role: Accessible.AlertMessage
    Accessible.name: message

    Timer { id: timer; interval: 3500 }

    SoftShadow { radius: 26; strength: 0.2; offsetY: 6 }
    Rectangle {
        id: pill
        width: row.implicitWidth + 40
        height: parent.height
        radius: height / 2
        color: Theme.ink
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 10
            Icon { name: "circle-check"; tint: "#7FD3A2"; size: 20; anchors.verticalCenter: parent.verticalCenter }
            AppText {
                text: root.message
                color: Theme.textOnDark
                font.pixelSize: Theme.body
                font.weight: Font.Medium
                wrapMode: Text.NoWrap
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
