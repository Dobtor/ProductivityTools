# -*- coding: utf-8 -*-

from . import controllers
from . import models
from . import wizards


def _create_default_note_stages_for_existing_users(env):
    """Post-init hook: Create default note stages for existing users

    This ensures all existing users get default note stages when the module
    is installed or upgraded.
    """
    # Get all internal users who don't have any note stages
    users = env['res.users'].search([
        ('share', '=', False),  # Only internal users
    ])

    NoteStage = env['note.stage']
    default_stages = [
        {'name': 'Notes', 'sequence': 1, 'fold': False},
        {'name': 'Meeting Minutes', 'sequence': 5, 'fold': False},
        {'name': 'Manuals', 'sequence': 10, 'fold': False},
        {'name': 'References', 'sequence': 50, 'fold': True},
    ]

    for user in users:
        # Check if user already has stages
        existing_stages = NoteStage.search_count([('user_id', '=', user.id)])
        if existing_stages > 0:
            continue

        # Create default stages for user
        for stage_vals in default_stages:
            NoteStage.create({
                **stage_vals,
                'user_id': user.id,
            })
