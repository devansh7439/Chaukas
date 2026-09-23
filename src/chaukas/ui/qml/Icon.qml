import QtQuick
import Chaukas

// A Lucide icon in any colour. Rendered at twice its size for crisp high-DPI output.
Image {
    id: root
    property string name: ""
    property color tint: Theme.ink
    property int size: 20

    width: size
    height: size
    sourceSize.width: size * 2
    sourceSize.height: size * 2
    source: name.length > 0 ? Theme.icon(name, tint) : ""
    fillMode: Image.PreserveAspectFit
    smooth: true
    mipmap: true
    Accessible.ignored: true
}
