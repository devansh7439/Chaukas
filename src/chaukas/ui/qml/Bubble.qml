import QtQuick
import QtQuick.Layouts
import Chaukas

// One line of the call log. Caller lines sit left in white, the user's right in grey,
// screen events centred. Detected tactics appear as tags under the caller's line.
Item {
    id: root
    required property var modelData
    readonly property bool isCaller: modelData.speaker === "caller"
    readonly property bool isUser: modelData.speaker === "user"
    readonly property bool isSystem: modelData.speaker === "system"
    property real maxBubble: width * 0.8

    width: ListView.view ? ListView.view.width : 400
    height: isSystem ? systemPill.height + 4 : column.implicitHeight + 4

    // Screen events: a centred pill
    Rectangle {
        id: systemPill
        visible: root.isSystem
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(root.width, systemRow.implicitWidth + 28)
        height: 36
        radius: 18
        color: Theme.accentSoft
        Row {
            id: systemRow
            anchors.centerIn: parent
            spacing: 8
            Icon { name: "monitor"; tint: Theme.accentDeep; size: 16; anchors.verticalCenter: parent.verticalCenter }
            AppText {
                text: root.modelData.text + "  ·  " + root.modelData.time
                color: Theme.accentDeep
                font.pixelSize: Theme.label
                font.weight: Font.DemiBold
                wrapMode: Text.NoWrap
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    ColumnLayout {
        id: column
        visible: !root.isSystem
        width: root.width
        spacing: 6

        AppText {
            Layout.alignment: root.isUser ? Qt.AlignRight : Qt.AlignLeft
            text: (root.isUser ? dashboard.labels.speaker_user : dashboard.labels.speaker_caller)
                  + "  ·  " + root.modelData.time
            color: Theme.inkMuted
            font.pixelSize: Theme.caption
            wrapMode: Text.NoWrap
        }

        Item {
            Layout.alignment: root.isUser ? Qt.AlignRight : Qt.AlignLeft
            implicitWidth: Math.min(root.maxBubble, lineText.implicitWidth + 36)
            implicitHeight: lineText.implicitHeight + 26

            SoftShadow { visible: root.isCaller; radius: 22; strength: 0.06; offsetY: 3 }
            Rectangle {
                anchors.fill: parent
                radius: 22
                color: root.isUser ? Theme.bubbleUser : Theme.raised
            }
            AppText {
                id: lineText
                anchors.fill: parent
                anchors.margins: 13
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                text: root.modelData.text
                font.pixelSize: Theme.body
                font.weight: Font.Medium
                lineHeight: 1.15
                elide: Text.ElideNone
            }
        }

        Flow {
            visible: root.modelData.tags.length > 0
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: root.modelData.tags
                Rectangle {
                    required property string modelData
                    width: tag.implicitWidth + 20
                    height: 26
                    radius: 13
                    color: Theme.accentSoft
                    AppText {
                        id: tag
                        anchors.centerIn: parent
                        text: parent.modelData
                        color: Theme.accentDeep
                        font.pixelSize: Theme.caption
                        font.weight: Font.DemiBold
                        wrapMode: Text.NoWrap
                    }
                }
            }
        }
    }
}
