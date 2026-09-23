import QtQuick
import QtQuick.Layouts
import Chaukas

// The evidence timeline: each reason with the moment it happened and what was said.
ColumnLayout {
    id: root
    property var reasons: []
    property int limit: 99
    property bool darkSurface: false
    property bool large: false

    spacing: large ? 12 : 8

    Repeater {
        model: root.reasons.slice(Math.max(0, root.reasons.length - root.limit))
        RowLayout {
            id: row
            required property var modelData
            Layout.fillWidth: true
            spacing: 14

            Rectangle {
                Layout.preferredWidth: root.large ? 44 : 36
                Layout.preferredHeight: Layout.preferredWidth
                Layout.alignment: Qt.AlignTop
                radius: width / 2
                color: root.darkSurface ? Qt.rgba(1, 1, 1, 0.12) : Theme.accentSoft
                Icon {
                    anchors.centerIn: parent
                    name: row.modelData.icon
                    tint: root.darkSurface ? Theme.textOnDark : Theme.accentDeep
                    size: root.large ? 20 : 16
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                AppText {
                    Layout.fillWidth: true
                    text: row.modelData.text
                    color: root.darkSurface ? Theme.textOnDark : Theme.ink
                    font.pixelSize: root.large ? Theme.bodyLarge + 1 : Theme.body
                    font.weight: Font.DemiBold
                }
                AppText {
                    visible: row.modelData.quote.length > 0
                    Layout.fillWidth: true
                    text: "“" + row.modelData.quote + "”"
                    color: root.darkSurface ? Theme.textOnDarkMuted : Theme.inkMuted
                    font.pixelSize: Theme.label
                    font.italic: true
                    maximumLineCount: 2
                }
            }

            AppText {
                Layout.alignment: Qt.AlignTop
                text: row.modelData.time
                color: root.darkSurface ? Theme.textOnDarkMuted : Theme.inkMuted
                font.pixelSize: Theme.label
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                wrapMode: Text.NoWrap
            }
        }
    }
}
