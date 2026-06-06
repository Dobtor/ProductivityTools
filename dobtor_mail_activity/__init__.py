# -*- coding: utf-8 -*-

from . import controllers
from . import models
from . import wizards


def _create_default_note_stages_for_existing_users(env):
    """Post-init hook: Create default note stages for existing users

    This ensures all existing users get default note stages when the module
    is installed or upgraded. Uses batch creation for efficiency.
    """
    # Get all internal users
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

    # Batch query users who already have stages
    env.cr.execute(
        "SELECT DISTINCT user_id FROM note_stage WHERE user_id IN %s",
        [tuple(users.ids)] if users.ids else [(0,)]
    )
    users_with_stages = {row[0] for row in env.cr.fetchall()}

    # Batch collect all vals
    vals_list = []
    for user in users:
        if user.id in users_with_stages:
            continue
        for stage_vals in default_stages:
            vals_list.append({
                **stage_vals,
                'user_id': user.id,
            })

    if vals_list:
        NoteStage.create(vals_list)


def _post_init_hook(env):
    """Post-init hook."""
    _create_default_note_stages_for_existing_users(env)
