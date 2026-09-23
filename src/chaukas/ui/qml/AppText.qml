import QtQuick
import Chaukas

// Text in the product typeface.
Text {
    font.family: Theme.fontFor(text, dashboard.language)
    font.pixelSize: Theme.body
    color: Theme.ink
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    elide: Text.ElideRight
}
