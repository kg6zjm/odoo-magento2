# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Guewen Baconnier
#    Copyright 2014 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

"""
Related Actions for Magento:

Related actions are associated with jobs.
When called on a job, they will return an action to the client.

"""

import functools
from odoo import exceptions, _
from .connector import get_environment
from odoo.addons.odoo_magento2_ept.models.unit.backend_adapter import GenericAdapter
from odoo.addons.odoo_magento2_ept.models.unit.binder import MagentoBinder
from odoo.addons.odoo_magento2_ept.models.backend.connector import ConnectorEnvironment, Binder


def unwrap_binding(session, job, id_pos=2, binder_class=Binder):
    """ Open a form view with the unwrapped record.

    For instance, for a job on a ``magento.product.product``,
    it will open a ``product.product`` form view with the unwrapped
    record.

    :param id_pos: position of the binding ID in the args
    :param binder_class: base class to search for the binder
    """
    binding_model = job.args[0]
    # shift one to the left because session is not in job.args
    binding_id = job.args[id_pos - 1]
    action = {
        'name': _('Related Record'),
        'type': 'ir.actions.act_window',
        'view_type': 'form',
        'view_mode': 'form',
    }
    # try to get an unwrapped record
    binding = session.env[binding_model].browse(binding_id)
    if not binding.exists():
        # it has been deleted
        return None
    env = ConnectorEnvironment(binding.backend_id, session, binding_model)
    binder = env.get_connector_unit(binder_class)
    try:
        model = binder.unwrap_model()
        record_id = binder.unwrap_binding(binding_id)
    except ValueError:
        # the binding record will be displayed
        action.update({
            'res_model': binding_model,
            'res_id': binding_id,
        })
    else:
        # the unwrapped record will be displayed
        action.update({
            'res_model': model,
            'res_id': record_id,
        })
    return action


unwrap_binding = functools.partial(unwrap_binding,
                                   binder_class=MagentoBinder)


def link(session, job, backend_id_pos=2, magento_id_pos=3):
    """ Open a Magento URL on the admin page to view/edit the record
    related to the job.
    """
    binding_model = job.args[0]
    # shift one to the left because session is not in job.args
    backend_id = job.args[backend_id_pos - 1]
    magento_id = job.args[magento_id_pos - 1]
    env = get_environment(session, binding_model, backend_id)
    adapter = env.get_connector_unit(GenericAdapter)
    try:
        url = adapter.admin_url(magento_id)
    except ValueError:
        raise exceptions.Warning(
            _('No admin URL configured on the backend or '
              'no admin path is defined for this record.')
        )

    action = {
        'type': 'ir.actions.act_url',
        'target': 'new',
        'url': url,
    }
    return action
