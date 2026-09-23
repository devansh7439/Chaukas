import QtQuick
import Chaukas

// A capsule tile with a white icon disc and a label (the reference's Workout / Meal tiles).
Item {
    id: root
    property string iconName: ""
    property string label: ""
    property bool checked: false
    property color tone: Theme.accent
    signal clicked()

    implicitWidth: 100
    implicitHeight: 124
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: label
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()

    Rectangle {
        id: capsule
        anchors.fill: parent
        radius: width / 2
        border.width: root.activeFocus ? 2 : 0
        border.color: Theme.focusRing
        scale: tap.pressed ? 0.97 : 1
        Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
        gradient: Gradient {
            GradientStop { position: 0.0; color: hover.hovered ? "#F4F4F4" : Theme.surfaceTop }
            GradientStop { position: 1.0; color: Theme.surface }
        }

        Rectangle {
            id: disc
            width: Math.min(64, capsule.width - 16)
            height: width
            radius: width / 2
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 10
            color: root.checked ? root.tone : Theme.raised
            Behavior on color { ColorAnimation { duration: Theme.normal } }
            SoftShadow { radius: disc.radius; strength: root.checked ? 0.25 : 0.1; offsetY: 4
                         tint: root.checked ? root.tone : "#000000" }
            Icon {
                anchors.centerIn: parent
                name: root.iconName
                tint: root.checked ? Theme.textOnAccent : Theme.ink
                size: 24
            }
        }

        AppText {
            anchors.top: disc.bottom
            anchors.topMargin: 12
            anchors.horizontalCenter: parent.horizontalCenter
            width: capsule.width - 8
            horizontalAlignment: Text.AlignHCenter
            text: root.label
            font.pixelSize: Theme.label
            font.weight: Font.Medium
            color: Theme.ink
            maximumLineCount: 2
        }
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: tap; onTapped: root.clicked() }
}
