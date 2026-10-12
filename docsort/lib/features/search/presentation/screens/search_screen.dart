import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_text_styles.dart';
import '../../../../core/widgets/skeleton_loader.dart';
import '../providers/search_provider.dart';

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _clearSearch() {
    _searchController.clear();
    ref.read(searchResultsProvider.notifier).onQueryChanged('');
  }

  @override
  Widget build(BuildContext context) {
    final query = ref.watch(searchQueryProvider);
    final resultsState = ref.watch(searchResultsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Document Search'),
        backgroundColor: AppColors.surfaceLowest,
        elevation: 1,
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(70),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: TextField(
              controller: _searchController,
              onChanged: (val) =>
                  ref.read(searchResultsProvider.notifier).onQueryChanged(val),
              decoration: InputDecoration(
                hintText:
                    'Search filenames, types, names, or extracted fields...',
                prefixIcon: const Icon(
                  Icons.search,
                  color: AppColors.textSecondary,
                ),
                suffixIcon: query.isNotEmpty
                    ? IconButton(
                        tooltip: 'Clear search',
                        icon: const Icon(
                          Icons.clear,
                          color: AppColors.textSecondary,
                        ),
                        onPressed: _clearSearch,
                      )
                    : null,
                filled: true,
                fillColor: AppColors.surfaceLow,
                contentPadding: const EdgeInsets.symmetric(vertical: 0),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
              ),
            ),
          ),
        ),
      ),
      body: SafeArea(
        child: resultsState.when(
          loading: () => ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: 5,
            separatorBuilder: (_, _) => const SizedBox(height: 16),
            itemBuilder: (context, index) => Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SkeletonLoader(width: 200, height: 20, borderRadius: 4),
                      const SizedBox(height: 8),
                      SkeletonLoader(
                        width: double.infinity,
                        height: 16,
                        borderRadius: 4,
                      ),
                      const SizedBox(height: 4),
                      SkeletonLoader(width: 150, height: 16, borderRadius: 4),
                    ],
                  ),
                ),
                const SizedBox(width: 16),
                const SkeletonLoader(width: 60, height: 40, borderRadius: 8),
              ],
            ),
          ),
          error: (_, _) => const Center(
            child: Text(
              'Could not complete the search. Please try again.',
              textAlign: TextAlign.center,
            ),
          ),
          data: (results) {
            if (query.isEmpty) {
              return Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      Icons.manage_search_rounded,
                      size: 80,
                      color: AppColors.outlineVariant,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'Search your document cabinet.',
                      style: AppTextStyles.bodyLg.copyWith(
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              );
            }

            if (results.isEmpty) {
              return CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverFillRemaining(
                    child: Center(
                      child: Text(
                        'No results found for "$query"',
                        style: AppTextStyles.bodyLg,
                      ),
                    ),
                  ),
                ],
              );
            }

            return RefreshIndicator(
              onRefresh: () async {
                ref.invalidate(searchResultsProvider);
              },
              child: ListView.separated(
                padding: const EdgeInsets.all(16),
                itemCount: results.length,
                separatorBuilder: (context, index) =>
                    const Divider(color: AppColors.outlineVariant),
                itemBuilder: (context, index) {
                  final item = results[index];
                  return ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(item.title, style: AppTextStyles.h2),
                    subtitle: Padding(
                      padding: const EdgeInsets.only(top: 8.0),
                      child: Text.rich(
                        TextSpan(
                          children: [
                            for (final segment in parseSearchSnippet(
                              item.snippet,
                            ))
                              TextSpan(
                                text: segment.text,
                                style: segment.highlighted
                                    ? AppTextStyles.bodySm.copyWith(
                                        color: AppColors.primary,
                                        fontWeight: FontWeight.w700,
                                      )
                                    : AppTextStyles.bodySm,
                              ),
                          ],
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: AppColors.secondaryContainer,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            item.type,
                            style: AppTextStyles.labelMd.copyWith(
                              color: AppColors.primary,
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${item.reviewStatus == 'verified' ? 'Verified' : 'Needs Review'} • OCR ${(item.ocrConfidence * 100).toInt()}%',
                          style: AppTextStyles.labelMd,
                        ),
                      ],
                    ),
                    onTap: () => context.go('/result/${item.id}'),
                  );
                },
              ),
            );
          },
        ),
      ),
    );
  }
}
