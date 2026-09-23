import QtQuick
import Chaukas

// A labelled button. Variants: "primary" (accent), "secondary" (white), "danger",
// "ghost" (for dark surfaces). Keyboard: Tab to focus, Enter/Space to press.
Item {
    id: root
    property string text: ""
    property string iconName: ""
    property string variant: "secondary"
    property color tone: Theme.accent
    signal clicked()

    readonly property bool filled: variant === "primary" || variant === "danger"
    readonly property color fill: variant === "danger" ? Theme.levelColor("critical")
                                 : variant === "primary" ? root.tone
                                 : variant === "ghost" ? Qt.rgba(1, 1, 1, 0.12)
                                 : Theme.raised
    readonly property color foreground: filled ? Theme.textOnAccent
                                       : variant === "ghost" ? Theme.textOnDark : Theme.ink

    implicitHeight: 48
    implicitWidth: row.implicitWidth + 40
    opacity: enabled ? 1 : 0.45
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: text
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onSpacePressed: if (enabled) clicked()

    SoftShadow {
        visible: root.variant !== "ghost" && root.enabled
        radius: height / 2
        strength: root.filled ? 0.16 : 0.07
        offsetY: 4
        tint: root.filled ? root.fill : "#000000"
    }

    Rectangle {
        id: face
        anchors.fill: parent
        radius: height / 2
        color: tap.pressed ? Qt.darker(root.fill, 1.08) : hover.hovered ? Qt.darker(root.fill, 1.03) : root.fill
        border.width: root.activeFocus ? 2 : 0
        border.color: Theme.focusRing
        scale: tap.pressed ? 0.97 : 1
        Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: Theme.fast } }

        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8
            Icon {
                visible: root.iconName.length > 0
                name: root.iconName
                tint: root.foreground
                size: 18
                anchors.verticalCenter: parent.verticalCenter
            }
            AppText {
                text: root.text
                color: root.foreground
                font.pixelSize: Theme.body
                font.weight: Font.DemiBold
                wrapMode: Text.NoWrap
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    HoverHandler { id: hover; cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    TapHandler { id: tap; enabled: root.enabled; onTapped: root.clicked() }
}
