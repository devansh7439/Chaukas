import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Chaukas

// Why Chaukas is warning you: the objective, every reason with its time, the facts, and
// what the user can do. The user always decides.
Item {
    id: root
    readonly property var view: dashboard.view

    RowLayout {
        anchors.fill: parent
        spacing: 28

        // Evidence timeline
        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: root.width - facts.Layout.preferredWidth - 28
            color: Theme.surfaceTop
            colorBottom: Theme.surface
            elevation: 0.35

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 32
                spacing: 18

                AppText {
                    Layout.fillWidth: true
                    text: dashboard.labels.why_title
                    font.pixelSize: 38
                    font.weight: Font.DemiBold
                    font.letterSpacing: -0.3
                    Accessible.role: Accessible.Heading
                }
                RowLayout {
                    spacing: 12
                    LevelChip { level: root.view.level; title: root.view.levelTitle }
                    AppText {
                        text: dashboard.view.callTime
                        color: Theme.inkMuted
                        font.pixelSize: Theme.body
                        wrapMode: Text.NoWrap
                    }
                }
                AppText {
                    Layout.fillWidth: true
                    text: root.view.objective
                    font.pixelSize: Theme.heading + 2
                    font.weight: Font.Medium
                }

                ScrollView {
                    id: scroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth

                    ReasonList {
                        width: scroll.availableWidth
                        reasons: root.view.reasons
                        large: true
                    }
                }

                AppText {
                    visible: root.view.reasons.length === 0
                    Layout.fillWidth: true
                    text: dashboard.labels.why_empty
                    color: Theme.inkMuted
                    font.pixelSize: Theme.bodyLarge
                }
            }
        }

        // Facts and decisions
        ColumnLayout {
            id: facts
            Layout.preferredWidth: Math.min(460, root.width * 0.4)
            Layout.maximumWidth: Layout.preferredWidth
            Layout.fillHeight: true
            spacing: 20

            Card {
                visible: root.view.fact.length > 0
                Layout.fillWidth: true
                Layout.preferredHeight: factLines.implicitHeight + 56
                color: Theme.darkTop
                colorBottom: Theme.darkBottom
                elevation: 1.2
                ColumnLayout {
                    id: factLines
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 28
                    spacing: 14
                    Icon { name: "info"; tint: Theme.accentGlow; size: 26 }
                    AppText {
                        Layout.fillWidth: true
                        text: root.view.fact
                        color: Theme.textOnDark
                        font.pixelSize: Theme.bodyLarge + 1
                        font.weight: Font.Medium
                        lineHeight: 1.2
                    }
                    AppText {
                        Layout.fillWidth: true
                        text: root.view.ignoreWarning
                        color: Theme.textOnDarkMuted
                        font.pixelSize: Theme.body
                        lineHeight: 1.2
                    }
                }
            }

            DecisionPanel { Layout.fillWidth: true; large: true }

            Item { Layout.fillHeight: true }
        }
    }
}
