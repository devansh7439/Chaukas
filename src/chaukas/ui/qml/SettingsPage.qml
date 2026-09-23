import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Chaukas

// Settings: language, trusted contact, capture exclusion. Saved on this PC only.
Item {
    id: root

    component Field: ColumnLayout {
        id: field
        property alias label: caption.text
        property alias value: input.text
        property alias hint: input.placeholderText
        property int inputHints: Qt.ImhNone
        spacing: 6
        AppText { id: caption; color: Theme.inkMuted; font.pixelSize: Theme.label; font.weight: Font.DemiBold }
        TextField {
            id: input
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            leftPadding: 20
            font.family: Theme.fontFor(text, dashboard.language)
            font.pixelSize: Theme.bodyLarge
            color: Theme.ink
            inputMethodHints: field.inputHints
            Accessible.name: caption.text
            background: Rectangle {
                radius: 26
                color: Theme.raised
                border.width: input.activeFocus ? 2 : 1
                border.color: input.activeFocus ? Theme.focusRing : Theme.track
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 26

        AppText {
            text: dashboard.labels.nav_settings
            font.pixelSize: Theme.display - 6
            font.weight: Font.DemiBold
            font.letterSpacing: -0.5
            Accessible.role: Accessible.Heading
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 24

            // Trusted contact
            Card {
                Layout.fillWidth: true
                Layout.preferredWidth: root.width - sideColumn.Layout.preferredWidth - 24
                Layout.preferredHeight: 380
                Layout.alignment: Qt.AlignTop
                elevation: 1
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 28
                    spacing: 16
                    AppText {
                        text: dashboard.labels.settings_contact
                        font.pixelSize: Theme.heading + 2
                        font.weight: Font.DemiBold
                    }
                    AppText {
                        Layout.fillWidth: true
                        text: dashboard.labels.settings_contact_hint
                        color: Theme.inkMuted
                        font.pixelSize: Theme.body
                    }
                    Field {
                        id: name
                        Layout.fillWidth: true
                        label: dashboard.labels.settings_name
                        value: dashboard.contactName
                    }
                    Field {
                        id: number
                        Layout.fillWidth: true
                        label: dashboard.labels.settings_number
                        value: dashboard.contactNumber
                        inputHints: Qt.ImhDialableCharactersOnly
                    }
                    PillButton {
                        variant: "primary"
                        iconName: "check"
                        text: dashboard.labels.settings_save
                        onClicked: dashboard.saveContact(name.value, number.value)
                    }
                }
            }

            ColumnLayout {
                id: sideColumn
                Layout.preferredWidth: Math.min(460, root.width * 0.42)
                Layout.maximumWidth: Layout.preferredWidth
                Layout.alignment: Qt.AlignTop
                spacing: 24

                // Language
                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    elevation: 1
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 28
                        spacing: 16
                        RowLayout {
                            spacing: 10
                            Icon { name: "languages"; size: 22 }
                            AppText {
                                text: dashboard.labels.settings_language
                                font.pixelSize: Theme.heading
                                font.weight: Font.DemiBold
                            }
                        }
                        Segmented {
                            options: [
                                { "label": "English", "value": "en" },
                                { "label": "हिन्दी", "value": "hi" }
                            ]
                            current: dashboard.language
                            onPicked: (value) => dashboard.setLanguage(value)
                        }
                    }
                }

                // Capture exclusion
                Card {
                    Layout.fillWidth: true
                    Layout.preferredHeight: captureColumn.implicitHeight + 56
                    elevation: 1
                    ColumnLayout {
                        id: captureColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 28
                        spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            AppText {
                                Layout.fillWidth: true
                                text: dashboard.labels.settings_capture
                                font.pixelSize: Theme.bodyLarge
                                font.weight: Font.DemiBold
                            }
                            Switch {
                                id: capture
                                checked: dashboard.captureExclusion
                                onToggled: dashboard.setCaptureExclusion(checked)
                                Accessible.name: dashboard.labels.settings_capture
                                indicator: Rectangle {
                                    implicitWidth: 56
                                    implicitHeight: 32
                                    radius: 16
                                    color: capture.checked ? Theme.accent : Theme.track
                                    border.width: capture.activeFocus ? 2 : 0
                                    border.color: Theme.focusRing
                                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                                    Rectangle {
                                        x: capture.checked ? parent.width - width - 4 : 4
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 24; height: 24; radius: 12
                                        color: Theme.raised
                                        Behavior on x { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
                                    }
                                }
                            }
                        }
                        AppText {
                            Layout.fillWidth: true
                            text: dashboard.labels.settings_capture_hint
                            color: Theme.inkMuted
                            font.pixelSize: Theme.body
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
