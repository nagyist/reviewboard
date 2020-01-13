from reviewboard.deprecation import RemovedInReviewBoard50Warning
    convert_line_endings,
    convert_to_unicode,
    get_filediffs_match,
    get_filediff_encodings,

class GetFileDiffsMatchTests(TestCase):
    """Unit tests for get_filediffs_match."""

    fixtures = ['test_scmtools', 'test_users']

    def setUp(self):
        super(GetFileDiffsMatchTests, self).setUp()

        review_request = self.create_review_request(create_repository=True)
        self.diffset = self.create_diffset(review_request)

    def test_with_filediff_none(self):
        """Testing get_filediffs_match with either filediff as None"""
        filediff = self.create_filediff(self.diffset, save=False)

        self.assertFalse(get_filediffs_match(filediff, None))
        self.assertFalse(get_filediffs_match(None, filediff))

        message = 'filediff1 and filediff2 cannot both be None'

        with self.assertRaisesMessage(ValueError, message):
            self.assertFalse(get_filediffs_match(None, None))

    def test_with_diffs_equal(self):
        """Testing get_filediffs_match with diffs equal"""
        filediff1 = self.create_filediff(self.diffset,
                                         diff=b'abc',
                                         save=False)
        filediff2 = self.create_filediff(self.diffset,
                                         diff=b'abc',
                                         save=False)

        self.assertTrue(get_filediffs_match(filediff1, filediff2))

    def test_with_deleted_true(self):
        """Testing get_filediffs_match with deleted flags both set"""
        self.assertTrue(get_filediffs_match(
            self.create_filediff(self.diffset,
                                 diff=b'abc',
                                 status=FileDiff.DELETED,
                                 save=False),
            self.create_filediff(self.diffset,
                                 diff=b'def',
                                 status=FileDiff.DELETED,
                                 save=False)))

    def test_with_sha256_equal(self):
        """Testing get_filediffs_match with patched SHA256 hashes equal"""
        filediff1 = self.create_filediff(self.diffset,
                                         diff=b'abc',
                                         save=False)
        filediff2 = self.create_filediff(self.diffset,
                                         diff=b'def',
                                         save=False)

        filediff1.extra_data['patched_sha256'] = 'abc123'
        filediff2.extra_data['patched_sha256'] = 'abc123'

        self.assertTrue(get_filediffs_match(filediff1, filediff2))

    def test_with_sha1_equal(self):
        """Testing get_filediffs_match with patched SHA1 hashes equal"""
        filediff1 = self.create_filediff(self.diffset,
                                         diff=b'abc',
                                         save=False)
        filediff2 = self.create_filediff(self.diffset,
                                         diff=b'def',
                                         save=False)

        filediff1.extra_data['patched_sha1'] = 'abc123'
        filediff2.extra_data['patched_sha1'] = 'abc123'

        self.assertTrue(get_filediffs_match(filediff1, filediff2))

    def test_with_sha1_not_equal(self):
        """Testing get_filediffs_match with patched SHA1 hashes not equal"""
        filediff1 = self.create_filediff(self.diffset,
                                         diff=b'abc',
                                         save=False)
        filediff2 = self.create_filediff(self.diffset,
                                         diff=b'def',
                                         save=False)

        filediff1.extra_data['patched_sha1'] = 'abc123'
        filediff2.extra_data['patched_sha1'] = 'def456'

        self.assertFalse(get_filediffs_match(filediff1, filediff2))

    def test_with_sha256_not_equal_and_sha1_equal(self):
        """Testing get_filediffs_match with patched SHA256 hashes not equal
        and patched SHA1 hashes equal
        """
        filediff1 = self.create_filediff(self.diffset,
                                         diff=b'abc',
                                         save=False)
        filediff2 = self.create_filediff(self.diffset,
                                         diff=b'def',
                                         save=False)

        filediff1.extra_data.update({
            'patched_sha256': 'abc123',
            'patched_sha1': 'abcdef',
        })
        filediff2.extra_data.update({
            'patched_sha256': 'def456',
            'patched_sha1': 'abcdef',
        })

        self.assertFalse(get_filediffs_match(filediff1, filediff2))


        patched = patch(diff=diff,
                        orig_file=old,
                        filename='foo.c')
            patch(diff=diff,
                  orig_file=old,
                  filename='foo.c')
        patched = patch(diff=diff,
                        orig_file=old,
                        filename='test.c')
        patched = patch(diff=diff,
                        orig_file=old,
                        filename='README')
        patched = patch(diff=diff,
                        orig_file=old,
                        filename='README')
        patched = patch(diff=diff,
                        orig_file=old,
                        filename='README')
        patched = patch(diff=diff,
                        orig_file=old,
                        filename='README')
class GetFileDiffEncodingsTests(TestCase):
    """Unit tests for get_filediff_encodings."""

    fixtures = ['test_scmtools']

    def setUp(self):
        super(GetFileDiffEncodingsTests, self).setUp()

        self.repository = self.create_repository(encoding='ascii,iso-8859-15')
        self.diffset = self.create_diffset(repository=self.repository)

    def test_with_stored_encoding(self):
        """Testing get_filediff_encodings with recorded FileDiff.encoding"""
        filediff = self.create_filediff(self.diffset,
                                        encoding='utf-16')

        self.assertEqual(get_filediff_encodings(filediff),
                         ['utf-16', 'ascii', 'iso-8859-15'])

    def test_with_out_stored_encoding(self):
        """Testing get_filediff_encodings without recorded FileDiff.encoding"""
        filediff = self.create_filediff(self.diffset)

        self.assertEqual(get_filediff_encodings(filediff),
                         ['ascii', 'iso-8859-15'])

    def test_with_custom_encodings(self):
        """Testing get_filediff_encodings with custom encoding_list"""
        filediff = self.create_filediff(self.diffset)

        self.assertEqual(
            get_filediff_encodings(filediff,
                                   encoding_list=['rot13', 'palmos']),
            ['rot13', 'palmos'])


        self.set_up_filediffs()

        self.assertEqual(get_original_file(filediff=filediff), b'bar\n')
            filediff=filediff,
            request=None,
            encoding_list=None))
        self.set_up_filediffs()

        self.assertEqual(get_original_file(filediff=filediff), b'baz\n')
        self.set_up_filediffs()

        self.assertEqual(get_original_file(filediff=filediff), b'')
        self.set_up_filediffs()

        self.assertEqual(get_original_file(filediff=filediff), b'foo\n')
        self.set_up_filediffs()

                filename=filename,
                error_output=_PATCH_GARBAGE_INPUT,
                orig_file=orig_file,
                new_file='tmp123-new',
                diff=b'',
                rejects=None)
            orig = get_original_file(filediff=filediff)
            orig = get_original_file(filediff=filediff)
        self.set_up_filediffs()

            orig = get_original_file(filediff=filediff)
            orig = get_original_file(filediff=filediff)
        self.set_up_filediffs()

            orig = get_original_file(filediff=filediff)
    def test_with_encoding_list(self):
        """Testing get_original_file with encoding_list is deprecated"""
        self.set_up_filediffs()

        filediff = FileDiff.objects.get(dest_file='bar',
                                        dest_detail='8e739cc',
                                        commit_id=1)

        message = (
            'The encoding_list parameter passed to get_original_file() is '
            'deprecated and will be removed in Review Board 5.0.'
        )

        with self.assert_warns(RemovedInReviewBoard50Warning, message):
            get_original_file(filediff, encoding_list=['ascii'])

    def test_with_filediff_with_encoding_set(self):
        """Testing get_original_file with FileDiff.encoding set"""
        content = 'hello world'.encode('utf-16')

        repository = self.create_repository()
        self.spy_on(repository.get_file,
                    call_fake=lambda *args, **kwargs: content)
        self.spy_on(convert_to_unicode)
        self.spy_on(convert_line_endings)

        diffset = self.create_diffset(repository=repository)
        filediff = self.create_filediff(diffset,
                                        encoding='utf-16')

        self.assertEqual(get_original_file(filediff=filediff), content)
        self.assertTrue(convert_to_unicode.called_with(
            content, ['utf-16', 'iso-8859-15']))
        self.assertTrue(convert_line_endings.called_with('hello world'))

    def test_with_filediff_with_repository_encoding_set(self):
        """Testing get_original_file with Repository.encoding set"""
        content = 'hello world'.encode('utf-16')

        repository = self.create_repository(encoding='utf-16')
        self.spy_on(repository.get_file,
                    call_fake=lambda *args, **kwargs: content)
        self.spy_on(convert_to_unicode)
        self.spy_on(convert_line_endings)

        diffset = self.create_diffset(repository=repository)
        filediff = self.create_filediff(diffset)

        self.assertEqual(get_original_file(filediff=filediff), content)
        self.assertTrue(convert_to_unicode.called_with(content, ['utf-16']))
        self.assertTrue(convert_line_endings.called_with('hello world'))
