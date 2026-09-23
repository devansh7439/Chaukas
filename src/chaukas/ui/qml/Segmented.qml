import QtQuick
import Chaukas

// A pill-shaped segmented control (the reference's Daily / Weekly / Monthly).
Rectangle {
    id: root
    property var options: []          // [{ "label": "...", "value": ... }]
    property var current
    signal picked(var value)

    implicitHeight: 46
    implicitWidth: row.implicitWidth + 8
    radius: height / 2
    color: Theme.surface

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2
        Repeater {
            model: root.options
            Item {
                id: option
                required property var modelData
                readonly property bool selected: modelData.value === root.current
                width: caption.implicitWidth + 36
                height: root.height - 8
                activeFocusOnTab: true
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.label
                Accessible.checked: selected
                Keys.onReturnPressed: root.picked(modelData.value)
                Keys.onSpacePressed: root.picked(modelData.value)

                SoftShadow { visible: option.selected; radius: height / 2; strength: 0.08; offsetY: 3 }
                Rectangle {
                    anchors.fill: parent
                    radius: height / 2
                    color: option.selected ? Theme.raised : "transparent"
                    border.width: option.activeFocus ? 2 : 0
                    border.color: Theme.focusRing
                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                }
                AppText {
                    id: caption
                    anchors.centerIn: parent
                    text: option.modelData.label
                    color: option.selected ? Theme.ink : Theme.inkMuted
                    font.pixelSize: Theme.body
                    font.weight: option.selected ? Font.DemiBold : Font.Medium
                    wrapMode: Text.NoWrap
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.picked(option.modelData.value) }
            }
        }
    }
}
