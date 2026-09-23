import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Chaukas

// The live call: what was said, what Chaukas noticed, and a box to try a line yourself.
// The reference's "AI Chatbot" panel.
Card {
    id: root
    color: Theme.surfaceTop
    colorBottom: Theme.surface
    elevation: 0.35
    radius: Theme.radiusCard + 4

    property string speaker: "caller"

    // Warm glow behind the header pill
    Canvas {
        id: glow
        width: 420
        height: 220
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const g = ctx.createRadialGradient(width / 2, 30, 0, width / 2, 30, width / 2)
            g.addColorStop(0.0, Qt.rgba(0.85, 0.45, 0.28, 0.30))
            g.addColorStop(1.0, Qt.rgba(0.85, 0.45, 0.28, 0.0))
            ctx.fillStyle = g
            ctx.fillRect(0, 0, width, height)
        }
    }

    // Header pill
    Item {
        id: header
        anchors.top: parent.top
        anchors.topMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        width: headerRow.implicitWidth + 32
        height: 44
        SoftShadow { radius: 22; strength: 0.22; offsetY: 4; tint: Theme.accent }
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.lighter(Theme.accent, 1.12) }
                GradientStop { position: 1.0; color: Theme.accent }
            }
        }
        Row {
            id: headerRow
            anchors.centerIn: parent
            spacing: 8
            Icon { name: "audio-lines"; tint: Theme.textOnAccent; size: 18; anchors.verticalCenter: parent.verticalCenter }
            AppText {
                text: dashboard.labels.live_call + "  ·  " + dashboard.view.callTime
                color: Theme.textOnAccent
                font.pixelSize: Theme.body
                font.weight: Font.DemiBold
                wrapMode: Text.NoWrap
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    ListView {
        id: log
        anchors.top: header.bottom
        anchors.topMargin: 18
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.bottom: chips.top
        anchors.bottomMargin: 14
        clip: true
        spacing: 14
        model: dashboard.transcript
        delegate: Bubble {}
        boundsBehavior: Flickable.StopAtBounds
        onCountChanged: Qt.callLater(positionViewAtEnd)
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Accessible.name: dashboard.labels.live_call

        // Empty state
        Column {
            visible: log.count === 0
            anchors.centerIn: parent
            width: parent.width * 0.7
            spacing: 12
            Rectangle {
                width: 56
                height: 56
                radius: 28
                color: Theme.raised
                anchors.horizontalCenter: parent.horizontalCenter
                Icon { anchors.centerIn: parent; name: "headphones"; tint: Theme.inkMuted; size: 24 }
            }
            AppText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: dashboard.labels.waiting
                color: Theme.inkMuted
                font.pixelSize: Theme.body
            }
        }
    }

    // What Chaukas currently sees, strongest first
    Row {
        id: chips
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.bottom: composerLabel.top
        anchors.bottomMargin: 14
        spacing: 12
        height: 70
        Repeater {
            model: dashboard.view.chips
            EvidenceChip {
                required property var modelData
                label: modelData.label
                percent: modelData.percent
            }
        }
        AppText {
            visible: dashboard.view.chips.length === 0
            anchors.verticalCenter: parent.verticalCenter
            text: dashboard.labels.no_evidence
            color: Theme.inkMuted
            font.pixelSize: Theme.body
            wrapMode: Text.NoWrap
        }
    }

    AppText {
        id: composerLabel
        anchors.left: composer.left
        anchors.leftMargin: 20
        anchors.bottom: composer.top
        anchors.bottomMargin: 8
        text: dashboard.labels.type_label
        color: Theme.inkMuted
        font.pixelSize: Theme.caption
        font.weight: Font.Medium
        wrapMode: Text.NoWrap
    }

    // "Type something": try a line as the caller or as yourself
    Item {
        id: composer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 22
        height: 62

        SoftShadow { radius: 31; strength: 0.08; offsetY: 4 }
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: Theme.raised
            border.width: input.activeFocus ? 2 : 0
            border.color: Theme.focusRing
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 8

            // Who is speaking
            Rectangle {
                id: speakerToggle
                Layout.preferredHeight: Theme.target
                Layout.preferredWidth: speakerText.implicitWidth + 30
                radius: height / 2
                color: root.speaker === "caller" ? Theme.accentSoft : Theme.bubbleUser
                activeFocusOnTab: true
                Accessible.role: Accessible.Button
                Accessible.name: speakerText.text
                Keys.onSpacePressed: root.speaker = root.speaker === "caller" ? "user" : "caller"
                border.width: activeFocus ? 2 : 0
                border.color: Theme.focusRing
                AppText {
                    id: speakerText
                    anchors.centerIn: parent
                    text: root.speaker === "caller" ? dashboard.labels.speaker_caller : dashboard.labels.speaker_user
                    color: root.speaker === "caller" ? Theme.accentDeep : Theme.ink
                    font.pixelSize: Theme.label
                    font.weight: Font.Bold
                    wrapMode: Text.NoWrap
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.speaker = root.speaker === "caller" ? "user" : "caller" }
            }

            TextField {
                id: input
                Layout.fillWidth: true
                Layout.fillHeight: true
                placeholderText: dashboard.labels.type_hint
                placeholderTextColor: Theme.inkFaint
                color: Theme.ink
                font.family: Theme.fontFor(text + placeholderText, dashboard.language)
                font.pixelSize: Theme.body
                background: Item {}
                verticalAlignment: TextInput.AlignVCenter
                Accessible.name: dashboard.labels.type_label
                onAccepted: send()
                function send() {
                    if (text.trim().length > 0) {
                        dashboard.say(text, root.speaker)
                        text = ""
                    }
                }
            }

            CircleButton {
                diameter: 44
                iconName: "send-horizontal"
                label: dashboard.labels.send
                enabled: input.text.trim().length > 0
                opacity: enabled ? 1 : 0.4
                onClicked: input.send()
            }
        }
    }
}
