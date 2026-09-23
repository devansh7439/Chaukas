import QtQuick
import Chaukas

// A round icon button with a glow in its own colour (the reference's orange bolt).
Item {
    id: root
    property string iconName: "zap"
    property color tone: Theme.accent
    property int diameter: 60
    property string label: ""
    signal clicked()

    width: diameter
    height: diameter
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: label
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()

    SoftShadow { radius: root.diameter / 2; strength: 0.3; spread: 2.2; offsetY: 5; tint: root.tone }

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        border.width: root.activeFocus ? 2 : 0
        border.color: Theme.focusRing
        scale: tap.pressed ? 0.94 : hover.hovered ? 1.04 : 1
        Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(root.tone, 1.18) }
            GradientStop { position: 1.0; color: root.tone }
        }
        Icon {
            anchors.centerIn: parent
            name: root.iconName
            tint: Theme.textOnAccent
            size: Math.round(root.diameter * 0.42)
        }
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: tap; onTapped: root.clicked() }
}
