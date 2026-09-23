import QtQuick
import Chaukas

// Pressure vs risk as two concentric arcs (the reference's Exercise / Stand card).
// Pressure is how hard the caller is pushing; risk is what remains after checking whether
// the speech is aimed at you, what is on screen, and the attack pattern.
Card {
    id: root
    readonly property int pressure: dashboard.view.pressurePercent
    readonly property int risk: dashboard.view.scorePercent

    color: Theme.surfaceTop
    colorBottom: Theme.surface
    elevation: 0.35

    Canvas {
        id: arcs
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width * 0.5
        antialiasing: true
        property real pressureValue: root.pressure / 100
        property real riskValue: root.risk / 100
        Behavior on pressureValue { NumberAnimation { duration: Theme.normal } }
        Behavior on riskValue { NumberAnimation { duration: Theme.normal } }
        onPressureValueChanged: requestPaint()
        onRiskValueChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const cx = 24
            const cy = height + 12
            const outer = height * 0.82
            const inner = height * 0.64
            const start = -Math.PI / 2
            function arc(r, value, colour, lineWidth) {
                ctx.lineWidth = lineWidth
                ctx.lineCap = "round"
                ctx.strokeStyle = Theme.track
                ctx.beginPath()
                ctx.arc(cx, cy, r, start, 0)
                ctx.stroke()
                if (value > 0) {
                    ctx.strokeStyle = colour
                    ctx.beginPath()
                    ctx.arc(cx, cy, r, start, start + (Math.PI / 2) * Math.min(1, value))
                    ctx.stroke()
                }
            }
            arc(outer, pressureValue, Theme.accent, 14)
            arc(inner, riskValue, Theme.ink, 14)
        }
    }

    Card {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 10
        width: parent.width * 0.5
        radius: Theme.radiusInner + 4
        elevation: 0.8

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            spacing: 18
            Repeater {
                model: [
                    { "label": dashboard.labels.pressure, "value": root.pressure, "dot": Theme.accent },
                    { "label": dashboard.labels.risk, "value": root.risk, "dot": Theme.ink }
                ]
                Column {
                    id: entry
                    required property var modelData
                    spacing: 2
                    Row {
                        spacing: 8
                        Rectangle {
                            width: 8; height: 8; radius: 4
                            color: entry.modelData.dot
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        AppText {
                            text: entry.modelData.label
                            color: Theme.inkMuted
                            font.pixelSize: Theme.body
                            wrapMode: Text.NoWrap
                        }
                    }
                    Row {
                        AppText {
                            id: number
                            text: entry.modelData.value
                            font.pixelSize: 26
                            font.weight: Font.DemiBold
                            wrapMode: Text.NoWrap
                        }
                        AppText {
                            text: "%"
                            font.pixelSize: Theme.bodyLarge
                            font.weight: Font.DemiBold
                            wrapMode: Text.NoWrap
                            anchors.baseline: number.baseline
                        }
                    }
                }
            }
        }
    }
}
