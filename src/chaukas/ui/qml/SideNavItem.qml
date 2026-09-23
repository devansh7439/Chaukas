import QtQuick
import Chaukas

// One sidebar destination: icon disc + label. The active one grows into a white disc.
Item {
    id: root
    property string iconName: ""
    property string label: ""
    property bool active: false
    signal clicked()

    width: 96
    height: 96
    activeFocusOnTab: true
    Accessible.role: Accessible.PageTab
    Accessible.name: label
    Accessible.selected: active
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()

    Item {
        id: discArea
        width: 72
        height: 72
        anchors.horizontalCenter: parent.horizontalCenter

        Rectangle {
            id: disc
            anchors.centerIn: parent
            width: root.active ? 72 : 52
            height: width
            radius: width / 2
            color: root.active ? Theme.raised : Qt.rgba(1, 1, 1, hover.hovered ? 0.18 : 0.09)
            border.width: root.activeFocus ? 2 : 0
            border.color: Theme.focusRing
            Behavior on width { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: Theme.fast } }

            SoftShadow { visible: root.active; radius: disc.radius; strength: 0.35; offsetY: 6 }

            Icon {
                anchors.centerIn: parent
                name: root.iconName
                tint: root.active ? Theme.accent : Theme.textOnDark
                size: root.active ? 30 : 22
            }
        }
    }

    AppText {
        anchors.top: discArea.bottom
        anchors.topMargin: 6
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.label
        color: root.active ? Theme.textOnDark : Theme.textOnDarkMuted
        font.pixelSize: Theme.label
        font.weight: root.active ? Font.DemiBold : Font.Medium
        wrapMode: Text.NoWrap
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: root.clicked() }
}
