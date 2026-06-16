"""
Email Log Model

Tracks all emails sent by the system for audit and debugging purposes.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class EmailLog(Base):
    """Model for tracking sent emails."""
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    to_email = Column(String(255), nullable=False, index=True)
    email_type = Column(String(50), nullable=False, index=True)
    subject = Column(String(500), nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)

    def __repr__(self):
        return f"<EmailLog(to={self.to_email}, type={self.email_type}, success={self.success})>"
