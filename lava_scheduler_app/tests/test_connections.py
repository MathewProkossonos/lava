# unit tests for primary and secondary connections
import os
import yaml
from lava_scheduler_app.models import (
    TestJob,
    DevicesUnavailableException,
    SubmissionException,
)
from lava_scheduler_app.tests.test_pipeline import YamlFactory
from lava_scheduler_app.tests.test_submission import TestCaseWithFactory


# TestCaseWithFactory cannot help causing too-many-ancestors, so ignore
# pylint: disable=too-many-ancestors

class YamlSshFactory(YamlFactory):

    def make_job_data(self, actions=None, **kw):
        sample_job_file = os.path.join(os.path.dirname(__file__), 'devices', 'qemu-ssh-guest.yaml')
        with open(sample_job_file, 'r') as test_support:
            data = yaml.load(test_support)
        data.update(kw)
        return data


class SecondaryConnections(TestCaseWithFactory):

    def setUp(self):
        super(SecondaryConnections, self).setUp()
        self.factory = YamlSshFactory()
        self.device_type = self.factory.make_device_type()

    def test_ssh_job_data(self):
        data = yaml.load(self.factory.make_job_yaml())
        self.assertNotIn('context', data)
        self.assertNotIn('timeout', data)
        self.assertIn('timeouts', data)
        self.assertIn('job', data['timeouts'])

    def test_make_ssh_guest_yaml(self):
        hostname = 'fakeqemu3'
        device = self.factory.make_device(self.device_type, hostname)
        try:
            jobs = TestJob.from_yaml_and_user(
                self.factory.make_job_yaml(),
                self.factory.make_user())
        except DevicesUnavailableException as exc:
            self.fail(exc)

        sub_id = []
        group_size = 0
        path = os.path.join(os.path.dirname(os.path.join(__file__)), 'devices')
        host_role = []
        for job in jobs:
            data = yaml.load(job.definition)
            params = data['protocols']['lava-multinode']
            params['target_group'] = 'replaced'
            if not group_size:
                group_size = params['group_size']
            if job.sub_id.endswith('.0'):
                self.assertFalse(job.dynamic_connection)
                self.assertEqual(job.requested_device_type.name, device.device_type.name)
                self.assertEqual(params['sub_id'], 0)
                sub_id.append(params['sub_id'])
                self.assertEqual(
                    data,
                    yaml.load(open(os.path.join(path, 'qemu-ssh-parent.yaml'), 'r').read())
                )
                self.assertEqual(job.device_role, 'host')
                host_role.append(job.device_role)
            else:
                self.assertTrue(job.dynamic_connection)
                self.assertNotIn(sub_id, params['sub_id'])
                sub_id.append(params['sub_id'])
                self.assertIsNone(job.requested_device_type)
                deploy = [action for action in data['actions'] if 'deploy' in action][0]
                self.assertEqual(deploy['deploy']['connection'], 'ssh')
                # validate each job
                if params['sub_id'] == 1:
                    self.assertEqual(
                        data,
                        yaml.load(open(os.path.join(path, 'qemu-ssh-guest-1.yaml'), 'r').read())
                    )
                elif params['sub_id'] == 2:
                    self.assertEqual(
                        data,
                        yaml.load(open(os.path.join(path, 'qemu-ssh-guest-2.yaml'), 'r').read())
                    )
                else:
                    self.fail("Unexpected sub_id parameter")
                self.assertIsNone(job.requested_device_type)
                self.assertIsNone(job.actual_device)
                self.assertIsNone(job.requested_device)
                host_role.append(data['host_role'])

        self.assertFalse(any(role for role in host_role if role != 'host'))
        self.assertEqual(len(sub_id), group_size)
        self.assertEqual(sub_id, range(0, group_size))

    def test_host_role(self):
        # need a full job to properly test the multinode YAML split
        hostname = 'fakeqemu3'
        self.factory.make_device(self.device_type, hostname)
        # create a new device to allow the submission to reach the multinode YAML test.
        hostname = 'fakeqemu4'
        self.factory.make_device(self.device_type, hostname)
        data = yaml.load(self.factory.make_job_yaml())
        data['protocols']['lava-multinode']['roles']['host']['count'] = 2
        self.assertRaises(
            SubmissionException, TestJob.from_yaml_and_user,
            yaml.dump(data), self.factory.make_user())

    def test_broken_link_yaml(self):
        hostname = 'fakeqemu3'
        self.factory.make_device(self.device_type, hostname)
        # create a new device to allow the submission to reach the multinode YAML test.
        hostname = 'fakeqemu4'
        self.factory.make_device(self.device_type, hostname)
        data = yaml.load(self.factory.make_job_yaml())
        deploy = [action['deploy'] for action in data['actions'] if 'deploy' in action]
        # replace working image with a broken URL
        for block in deploy:
            block['image'] = 'http://localhost/unknown/invalid.gz'
        try:
            jobs = TestJob.from_yaml_and_user(
                self.factory.make_job_yaml(),
                self.factory.make_user())
        except DevicesUnavailableException as exc:
            self.fail(exc)
        self.assertEqual(
            jobs[0].sub_id,
            "%d.%d" % (int(jobs[0].id), 0))
