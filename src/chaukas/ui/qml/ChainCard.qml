import QtQuick
import Chaukas

// The attack pattern as a route (the reference's dark Distance card): each step of the
// best-matching attack is a node; the steps seen so far are traced in copper.
Card {
    id: root
    readonly property var chain: dashboard.view.chain

    color: Theme.darkTop
    colorBottom: Theme.darkBottom
    elevation: 1.2
    Accessible.role: Accessible.StaticText
    Accessible.name: dashboard.labels.attack_pattern + ": " + chain.name + ", " + chain.stepsText

    Canvas {
        id: route
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 22
        height: parent.height * 0.42
        antialiasing: true
        property var steps: root.chain.steps
        onStepsChanged: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const n = Math.max(steps.length, 5)
            const points = []
            for (let i = 0; i < n; i++) {
                const x = 8 + (width - 16) * i / (n - 1)
                const y = (i % 2 === 0) ? height * 0.78 : height * 0.18
                points.push({ x: x, y: y })
            }
            const count = steps.length
            for (let i = 0; i < n - 1; i++) {
                const seen = i + 1 < count && steps[i].seen && steps[i + 1].seen
                ctx.strokeStyle = seen ? Theme.accent : Qt.rgba(1, 1, 1, 0.22)
                ctx.lineWidth = seen ? 4 : 3
                ctx.lineCap = "round"
                ctx.beginPath()
                ctx.moveTo(points[i].x, points[i].y)
                ctx.lineTo(points[i + 1].x, points[i + 1].y)
                ctx.stroke()
            }
            for (let i = 0; i < n; i++) {
                const seen = i < count && steps[i].seen
                ctx.fillStyle = seen ? Theme.accent : Qt.rgba(1, 1, 1, 0.35)
                ctx.beginPath()
                ctx.arc(points[i].x, points[i].y, seen ? 6 : 4, 0, 2 * Math.PI)
                ctx.fill()
            }
        }
    }

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.right: parent.right
        anchors.rightMargin: 20
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 22
        spacing: 3
        AppText {
            text: dashboard.labels.attack_pattern
            color: Theme.textOnDarkMuted
            font.pixelSize: Theme.body
            wrapMode: Text.NoWrap
        }
        AppText {
            width: parent.width
            text: root.chain.name
            color: Theme.textOnDark
            font.pixelSize: 24
            font.weight: Font.DemiBold
            maximumLineCount: 1
        }
        AppText {
            visible: root.chain.total > 0
            text: root.chain.stepsText
            color: Theme.textOnDarkMuted
            font.pixelSize: Theme.label
            wrapMode: Text.NoWrap
        }
    }
}
