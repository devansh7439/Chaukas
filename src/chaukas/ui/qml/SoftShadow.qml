import QtQuick

// A soft drop shadow built from stacked translucent rounded rectangles. No shaders, so it
// renders the same with the GPU and with the software renderer (VMs, Device Cloud).
Item {
    id: root
    property real radius: 24
    property int layers: 8
    property real spread: 2.4
    property real offsetY: 6
    property real strength: 0.08
    property color tint: "#000000"

    anchors.fill: parent
    z: -1

    Repeater {
        model: root.layers
        Rectangle {
            required property int index
            readonly property real grow: (index + 1) * root.spread
            x: -grow
            y: -grow + root.offsetY
            width: root.width + 2 * grow
            height: root.height + 2 * grow
            radius: root.radius + grow
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, root.strength / root.layers)
        }
    }
}
