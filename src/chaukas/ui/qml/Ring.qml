import QtQuick
import Chaukas

// A progress ring (the reference's small orange rings on the Running / Push up cards).
Canvas {
    id: root
    property real value: 0          // 0..1
    property color tone: Theme.accent
    property color trackColour: Theme.track
    property real lineWidth: 4

    implicitWidth: 38
    implicitHeight: 38
    antialiasing: true
    onValueChanged: requestPaint()
    onToneChanged: requestPaint()

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        const r = Math.min(width, height) / 2 - lineWidth
        const cx = width / 2
        const cy = height / 2
        ctx.lineWidth = lineWidth
        ctx.lineCap = "round"
        ctx.strokeStyle = trackColour
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, 2 * Math.PI)
        ctx.stroke()
        if (value > 0) {
            ctx.strokeStyle = tone
            ctx.beginPath()
            ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * Math.min(1, value))
            ctx.stroke()
        }
    }
}
