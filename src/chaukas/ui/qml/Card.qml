import QtQuick
import Chaukas

// A rounded surface. elevation 0 = inset (flat), 1 = raised with a soft shadow.
Item {
    id: root
    property color color: Theme.raised
    property color colorBottom: color
    property real radius: Theme.radiusCard
    property real elevation: 1
    property color shadowTint: "#000000"
    default property alias content: body.data

    SoftShadow {
        visible: root.elevation > 0
        radius: root.radius
        strength: 0.07 * root.elevation
        offsetY: 5 * root.elevation
        tint: root.shadowTint
    }

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        border.width: root.elevation > 0 ? 1 : 0
        border.color: Qt.rgba(1, 1, 1, 0.7)
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.color }
            GradientStop { position: 1.0; color: root.colorBottom }
        }
    }

    Item {
        id: body
        anchors.fill: parent
    }
}
