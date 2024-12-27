from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                            QTextEdit, QPushButton, QLabel, QCheckBox)
from PyQt6.QtCore import Qt

class CommentPreviewDialog(QDialog):
    def __init__(self, parent=None, comment_text="", spinner=None, total_profiles=0, current_row=0):
        super().__init__(parent)
        self.spinner = spinner
        self.total_profiles = total_profiles
        self.current_row = current_row
        self.init_ui()
        self.comment_text = comment_text
        self.text_edit.setPlainText(comment_text)
        self.update_preview()

    def init_ui(self):
        self.setWindowTitle("Comment Preview")
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout()
        
        # Input section
        input_layout = QVBoxLayout()
        input_layout.addWidget(QLabel("Enter comment with spin syntax:"))
        self.text_edit = QTextEdit()
        self.text_edit.textChanged.connect(self.update_preview)
        input_layout.addWidget(self.text_edit)
        
        # Preview section
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(QLabel("Preview of some possible variations:"))
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        
        # Help text
        help_text = """
Syntax Guide:
- Use {option1|option2|option3} for alternatives
- Use [optional text] for 50% chance inclusion
- Nest spinning: {Great|Awesome} {post|content}!
Example: {Hi|Hey|Hello} [there]! {This is|That's} {great|amazing}!

The bot will randomly select one variation when posting.
        """
        help_label = QLabel(help_text)
        help_label.setStyleSheet("color: gray; font-size: 10px;")
        
        # Add checkbox before buttons
        self.apply_across = QCheckBox("Apply across other profiles")
        remaining_profiles = self.total_profiles - self.current_row - 1
        if remaining_profiles > 0:
            self.apply_across.setToolTip(f"Will apply unique variations to the next {remaining_profiles} profiles")
        else:
            self.apply_across.setEnabled(False)
            self.apply_across.setToolTip("No remaining profiles to apply variations to")
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        
        # Create a container for the checkbox and button
        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.apply_across)
        bottom_layout.addStretch()
        bottom_layout.addWidget(ok_button)
        
        # Add all layouts
        layout.addLayout(input_layout)
        layout.addLayout(preview_layout)
        layout.addWidget(help_label)
        layout.addLayout(bottom_layout)
        
        self.setLayout(layout)

    def update_preview(self):
        if not self.spinner:
            return
            
        text = self.text_edit.toPlainText()
        # Show 5 random examples
        preview_text = "\n\n".join(
            f"Example {i+1}:\n{self.spinner.spin(text)}" 
            for i in range(5)
        )
        self.preview_text.setPlainText(preview_text)

    def get_comment(self):
        return self.text_edit.toPlainText()
        
    def should_apply_across(self):
        return self.apply_across.isChecked()